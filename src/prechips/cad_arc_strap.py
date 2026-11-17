"""Bindings for a flat arc strap cut from a blank clamped to a fixture plate.

The strap is a thin flat whose long edges are two concentric arcs about a
centre on the model's Y axis, closed at each end by a tip land and an end
face, with one reamed hub hole on the Y axis. Model X runs along the strap,
symmetric about X0; Y points from the outer (bottom) arc toward the arc
centre; Z is through the thickness, the mid-plane at Z0.

With the plan's plate-hold parameters the adapter also places the strap in
its blank: setup X from the blank's left end, Y from the fence into the blank,
the outer arc toward the clamps.
"""

import itertools
import math
import re
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _all_or_none,
    _band,
    _blank_mm,
    _edge_breaks,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
)

_FEATURES = {
    "hub_hole",
    "broad_face_pos_z",
    "broad_face_neg_z",
    "top_arc",
    "bottom_arc",
    "tip_land_pos_x",
    "tip_land_neg_x",
    "end_face_pos_x",
    "end_face_neg_x",
}
# Every plate-hold parameter, required together once any is declared; the
# clamps are clamp_1_x_mm, clamp_2_x_mm, ... (plan parameters are numbers).
_HOLD = (
    "hub_x_mm",
    "hub_y_mm",
    "clamp_1_x_mm",
    "clamp_2_x_mm",
    "tab_width_mm",
    "outline_cutter_dia_mm",
    "outline_finish_stock_mm",
    "margin_min_mm",
    "plate_start_x_mm",
    "plate_length_mm",
)
_CLAMP = re.compile(r"clamp_\d+_x_mm")
_FACES = ("face_finish_stock_mm", "blank_thickness_min_in", "blank_thickness_max_in")
_TOLERANCE = 1e-6


def _point(feature: dict, key: str, where: str) -> tuple[float, float]:
    """A model point in the strap's mid-plane, as (x, y)."""
    value = feature.get(key)
    if not isinstance(value, list) or len(value) != 3:
        raise CadError(f"{where}.{key}: expected a model point")
    x, y, z = (_number(item, f"{where}.{key}") for item in value)
    if abs(z) > _TOLERANCE:
        raise CadError(f"{where}.{key}: expected a point in the mid-plane")
    return x, y


def _same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=0, abs_tol=_TOLERANCE)


def _feature(features: dict, name: str, kind: str) -> dict:
    item = features[name]
    if (
        not isinstance(item, dict)
        or item.get("kind") != kind
        or item.get("frame") != "model"
    ):
        raise CadError(f"{name}: expected a model-frame {kind}")
    return item


def _same_point(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return _same(a[0], b[0]) and _same(a[1], b[1])


def _mirrored(
    features: dict, stem: str, bands: tuple[str, ...], points: tuple[str, ...]
) -> dict:
    """The +X member of a mirrored face pair whose bands and points agree."""
    pos = _feature(features, f"{stem}_pos_x", "face")
    neg = _feature(features, f"{stem}_neg_x", "face")
    for key in bands:
        if _band(pos, key, f"{stem}_pos_x") != _band(neg, key, f"{stem}_neg_x"):
            raise CadError(f"{stem}: the two ends disagree on {key}")
    for key in points:
        x, y = _point(neg, key, f"{stem}_neg_x")
        if not _same_point(_point(pos, key, f"{stem}_pos_x"), (-x, y)):
            raise CadError(f"{stem}: the two ends' {key} points are not mirrored")
    return pos


def _clamps(parameters: dict) -> list[float]:
    """Clamp stations ``clamp_N_x_mm`` from 1, ascending along the blank."""
    stations = []
    while f"clamp_{len(stations) + 1}_x_mm" in parameters:
        key = f"clamp_{len(stations) + 1}_x_mm"
        stations.append(_number(parameters[key], f"process.{key}"))
    if sum(1 for key in parameters if _CLAMP.fullmatch(key)) != len(stations):
        raise CadError("process.clamp_N_x_mm: number the clamps from 1 without gaps")
    if any(low >= high for low, high in itertools.pairwise(stations)):
        raise CadError("process.clamp_N_x_mm: expected ascending stations")
    return stations


def load_arc_strap(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the strap's limits, envelope and, when declared, its plate hold."""
    raw, values, features = _read_manifest(path, part, "arc_strap")
    _model_frame(raw)
    if features.keys() != _FEATURES:
        raise CadError(f"cad.features: expected exactly {', '.join(sorted(_FEATURES))}")

    # Thickness: both broad faces carry the one band, about the mid-plane.
    faces = [
        _feature(features, f"broad_face_{side}_z", "face") for side in ("pos", "neg")
    ]
    thickness = _band(faces[0], "thickness", "broad_face_pos_z")
    nominal = _positive(
        faces[0].get("thickness_nominal"), "broad_face_pos_z.thickness_nominal"
    )
    for face, sign, name in zip(
        faces, (1, -1), ("broad_face_pos_z", "broad_face_neg_z")
    ):
        plane = face.get("plane")
        if (
            _band(face, "thickness", name) != thickness
            or face.get("thickness_nominal") != nominal
            or not isinstance(plane, dict)
            or plane.get("axis") != "z"
            or not _same(
                _number(plane.get("value"), f"{name}.plane"), sign * nominal / 2
            )
        ):
            raise CadError(f"{name}: expected the thickness band about the mid-plane")
    if not thickness[0] <= nominal <= thickness[1]:
        raise CadError("broad_face_pos_z.thickness_nominal: outside thickness band")
    _inch_limits(values, "thickness", thickness)
    values["thickness_mm"] = nominal

    # Hub hole: reamed through, on the Y axis.
    hub = _feature(features, "hub_hole", "hole")
    hub_x, hub_y = _point(hub, "at", "hub_hole")
    if (
        hub_x != 0
        or hub.get("axis") != [0, 0, 1]
        or hub.get("thru") is not True
        or hub.get("process") != "ream"
    ):
        raise CadError("hub_hole: expected a reamed through hole on the Y axis")
    _inch_limits(values, "hub_dia", _band(hub, "dia", "hub_hole"))

    # The two arcs share a centre on the Y axis; each edge height is taken
    # from the hub hole along that axis.
    arcs = {}
    for name, key, sign in (
        ("top_arc", "height_above_pivot", 1),
        ("bottom_arc", "height_below_pivot", -1),
    ):
        arc = _feature(features, name, "profile")
        if arc.get("height_from") != "hub_hole":
            raise CadError(f"{name}: expected an edge height from hub_hole")
        height = _band(arc, key, name)
        _inch_limits(values, name.replace("arc", "height"), height)
        radius = _band(arc, "radius", name)
        _inch_limits(values, name.replace("arc", "radius"), radius)
        centre = _point(arc, "arc_centre", name)
        edge = _point(arc, "edge_on_axis", name)
        r = _positive(arc.get("radius_nominal"), f"{name}.radius_nominal")
        h = _positive(arc.get(f"{key}_nominal"), f"{name}.{key}_nominal")
        if (
            centre[0] != 0
            or edge[0] != 0
            or not _same(centre[1] - r, edge[1])
            or not _same(hub_y + sign * h, edge[1])
            or not height[0] <= h <= height[1]
            or not radius[0] <= r <= radius[1]
        ):
            raise CadError(f"{name}: arc, edge height and hub hole disagree")
        ends = arc.get("ends")
        if not isinstance(ends, list) or len(ends) != 2:
            raise CadError(f"{name}.ends: expected the arc's two end points")
        low, end = sorted(_point({"p": p}, "p", f"{name}.ends") for p in ends)
        if not _same_point(end, (-low[0], low[1])):
            raise CadError(f"{name}.ends: not mirrored about the Y axis")
        if end[0] <= 0 or not _same(math.hypot(end[0], centre[1] - end[1]), r):
            raise CadError(f"{name}.ends: not on the arc")
        arcs[name] = {"centre_y": centre[1], "radius": r, "edge_y": edge[1], "end": end}
    top, bottom = arcs["top_arc"], arcs["bottom_arc"]
    if (
        not _same(top["centre_y"], bottom["centre_y"])
        or top["radius"] >= bottom["radius"]
    ):
        raise CadError("top_arc, bottom_arc: expected concentric arcs, top inside")

    # Ends: tip land from the top arc's end to the corner, end face from the
    # corner to its foot on the bottom arc.
    land = _mirrored(
        features,
        "tip_land",
        ("land_length", "land_angle_deg", "corner_station"),
        ("inner_end", "corner"),
    )
    face = _mirrored(features, "end_face", ("foot_station",), ("corner", "foot"))
    corner = _point(land, "corner", "tip_land_pos_x")
    foot = _point(face, "foot", "end_face_pos_x")
    if (
        land.get("station_from") != "hub_hole"
        or face.get("station_from") != "hub_hole"
        or not _same_point(_point(land, "inner_end", "tip_land_pos_x"), top["end"])
        or not _same_point(_point(face, "corner", "end_face_pos_x"), corner)
        or not _same_point(foot, bottom["end"])
    ):
        raise CadError("tip_land, end_face: the end outline does not close")
    _inch_limits(values, "tip_length", _band(land, "land_length", "tip_land_pos_x"))
    angle = _band(land, "land_angle_deg", "tip_land_pos_x")
    values["tip_angle_min_deg"], values["tip_angle_max_deg"] = angle
    for key, band, at in (
        ("corner_station", _band(land, "corner_station", "tip_land_pos_x"), corner[0]),
        ("foot_station", _band(face, "foot_station", "end_face_pos_x"), foot[0]),
    ):
        if not band[0] <= at <= band[1]:
            raise CadError(f"{key}: the outline point lies outside its band")
        _inch_limits(values, key, band)
    overall = _positive(
        face.get("overall_length_ref"), "end_face_pos_x.overall_length_ref"
    )
    if not _same(overall, 2 * corner[0]):
        raise CadError("end_face_pos_x.overall_length_ref: not corner to corner")
    values["overall_length_mm"] = overall
    values["overall_length_in"] = overall / 25.4
    # Bounding height: the top arc's ends above the bottom arc's lowest point.
    height = top["end"][1] - bottom["edge_y"]
    values["width_mm"] = bottom["radius"] - top["radius"]
    # Mid-plane outline for the setup pictures, model mm.
    values["outline"] = {
        "hub_y": hub_y,
        "centre_y": top["centre_y"],
        "top_radius": top["radius"],
        "bottom_radius": bottom["radius"],
        "top_end": top["end"],
        "corner": corner,
        "foot": foot,
        "bottom_y": bottom["edge_y"],
    }
    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    envelope = (
        StockAxis("length", "blank_length_in", overall),
        StockAxis("width", "blank_width_in", height),
        StockAxis("thickness", "blank_thickness_in", nominal),
    )
    _face_levels(values, parameters)
    _plate_hold(values, parameters)
    return CadData(values, StockRequirement("in", envelope), path.resolve())


def _face_levels(values: dict, parameters: dict) -> None:
    """Fixed facing heights above the plate top, both faces skimmed equally.

    Face 1 is roughed at the nominal blank less its share, face 2 to the
    finished thickness plus the finish stock on both faces; then one finish
    pass per face. The posted heights are fixed, so the thinnest blank the
    plan admits must still clean up on face 1.
    """
    if not _all_or_none(parameters, _FACES, "the facing heights"):
        return
    if "blank_thickness_mm" not in values:
        raise CadError("process.face_finish_stock_mm: also need blank_thickness_in")
    stock = _positive(
        parameters["face_finish_stock_mm"], "process.face_finish_stock_mm"
    )
    blank = values["blank_thickness_mm"]
    low = (
        _positive(
            parameters["blank_thickness_min_in"], "process.blank_thickness_min_in"
        )
        * 25.4
    )
    high = (
        _positive(
            parameters["blank_thickness_max_in"], "process.blank_thickness_max_in"
        )
        * 25.4
    )
    if not low <= blank <= high:
        raise CadError("process.blank_thickness_in: outside its own min/max band")
    finished = values["thickness_mm"]
    rough = (blank - finished) / 2 - stock
    if rough <= 0:
        raise CadError(
            "process.face_finish_stock_mm: leaves nothing for the rough passes"
        )
    levels = [blank - rough, finished + 2 * stock, finished + stock]
    if low - levels[0] <= 0:
        raise CadError(
            f"process.blank_thickness_min_in: a {low / 25.4:.4f} in blank is not "
            f"cleaned up by the first rough face at {levels[0] / 25.4:.4f} in"
        )
    for name, level in zip(
        ("rough_face_1", "rough_face_2", "finish_face_1"), levels, strict=True
    ):
        values[f"{name}_z_mm"] = level
        values[f"{name}_z_in"] = level / 25.4
    # Deepest rough cut: the thickest blank's first face.
    values["face_rough_doc_mm"] = high - levels[0]
    values["face_finish_doc_mm"] = stock


def _plate_hold(values: dict, parameters: dict) -> None:
    """Place the strap in its blank on the plate; refuse a thin margin.

    Setup X runs from the blank's left end, the hub hole at ``hub_x_mm``;
    the fence is at Y0 and the hub ``hub_y_mm`` into the blank, the bottom
    arc toward the clamps on the far edge. The rough slot's outer wall lies
    the cutter Ø plus the finish stock outside the strap's edge; what is left
    of the blank beyond it is the margin strip a clamp bears on and a tab
    joins to.
    """
    if not _all_or_none(parameters, _HOLD, "the plate hold"):
        return
    for key in ("length", "width"):
        if f"blank_{key}_mm" not in values:
            raise CadError(f"process.hub_x_mm: also need blank_{key}_in")
    outline = values["outline"]
    hub_x = _positive(parameters["hub_x_mm"], "process.hub_x_mm")
    hub_y = _positive(parameters["hub_y_mm"], "process.hub_y_mm")
    cutter = _positive(
        parameters["outline_cutter_dia_mm"], "process.outline_cutter_dia_mm"
    )
    stock = _positive(
        parameters["outline_finish_stock_mm"], "process.outline_finish_stock_mm"
    )
    minimum = _positive(parameters["margin_min_mm"], "process.margin_min_mm")
    tab = _positive(parameters["tab_width_mm"], "process.tab_width_mm")
    reach = cutter + stock
    length, width = values["blank_length_mm"], values["blank_width_mm"]
    half = outline["corner"][0]
    part = [hub_x - half, hub_x + half]
    if part[0] - reach < 0 or part[1] + reach > length:
        raise CadError(
            f"process.hub_x_mm: the outline slot ({reach:g} mm outside the strap, "
            f"{part[0]:.3f}..{part[1]:.3f} mm) runs off the blank's end"
        )
    values["part_x_mm"] = part
    # Cutter-centre travel of the rough slot along X.
    travel = stock + cutter / 2
    values["outline_x_mm"] = [part[0] - travel, part[1] + travel]
    values["slot_reach_mm"] = reach
    # The blank less both slots: the section that still bends as one beam
    # while the outline is roughed.
    values["slotted_width_mm"] = width - 2 * cutter
    values["tab_length_mm"] = reach
    # Fence side: the top arc's ends are the strap's nearest points. The strip
    # left there lies against the fence for its whole length; it is refused
    # only when the slot would cut the fence, and bound for the plan to print.
    fence = hub_y - (outline["top_end"][1] - outline["hub_y"]) - reach
    if fence <= 0:
        raise CadError(
            f"process.hub_y_mm: the outline slot reaches {-fence:.3f} mm into the fence"
        )
    values["fence_margin_mm"] = fence

    # The slot's outer wall is the bottom arc offset outward along its normal.
    wall = outline["bottom_radius"] + reach

    def clamp_margin(x: float) -> float:
        """Strip between the slot and the clamped edge, ``x`` from the hub."""
        y = outline["centre_y"] - math.sqrt(wall**2 - x**2)
        return width - hub_y + (y - outline["hub_y"])

    # Clamp side: the bottom arc comes nearest the clamped edge on the hub's
    # centre line, where the strip is narrowest.
    front = clamp_margin(0)
    if front <= 0:
        raise CadError(
            f"process.hub_y_mm: the outline slot runs {-front:.3f} mm off the "
            "blank's clamped edge at the hub"
        )
    values["front_margin_mm"] = front
    # One tab at every clamp: the only stations where a tab is held down.
    clamps = _clamps(parameters)
    if clamps[0] < 0 or clamps[-1] > length:
        raise CadError("process.clamp_N_x_mm: off the blank")
    margins = []
    for number, station in enumerate(clamps, 1):
        # A tab joins the bottom arc to the clamped margin.
        x = abs(station - hub_x)
        if x + tab / 2 > outline["foot"][0]:
            raise CadError(
                f"process.clamp_{number}_x_mm: the tab at {station:g} mm is not on "
                "the bottom arc"
            )
        # Narrowest under the tab: at its edge nearer the hub.
        margin = clamp_margin(max(x - tab / 2, 0))
        if margin < minimum:
            raise CadError(
                f"process.clamp_{number}_x_mm: at {station:g} mm the outline slot "
                f"leaves a {margin:.3f} mm margin strip, under margin_min_mm "
                f"{minimum:g} mm"
            )
        margins.append(margin)
    values["clamp_x_mm"] = clamps
    values["clamp_margin_mm"] = margins
    start = _number(parameters["plate_start_x_mm"], "process.plate_start_x_mm")
    plate = [
        start,
        start + _positive(parameters["plate_length_mm"], "process.plate_length_mm"),
    ]
    if plate[0] > 0 or plate[1] < length:
        raise CadError("process.plate_start_x_mm: the plate does not back the blank")
    values["plate_x_mm"] = plate
    values["hub_x_in"] = hub_x / 25.4
    values["hub_y_in"] = hub_y / 25.4
    values["clamp_stations_in"] = ", ".join(f"{x / 25.4:.2f}" for x in clamps)
    # The relief hole is fixed in the plate, hub_x_mm from its end stop; the
    # hub hole is drilled that far from the blank's own end.
    if _all_or_none(
        parameters,
        ("hub_relief_dia_mm", "x_stop_tolerance_mm"),
        "the hub relief hole",
    ):
        relief = _positive(parameters["hub_relief_dia_mm"], "process.hub_relief_dia_mm")
        slack = _positive(
            parameters["x_stop_tolerance_mm"], "process.x_stop_tolerance_mm"
        )
        clear = (relief - values["hub_dia_band_mm"][1]) / 2
        if clear < slack:
            raise CadError(
                f"process.hub_relief_dia_mm: the relief hole leaves {clear:.3f} mm "
                f"round the hub hole, under x_stop_tolerance_mm {slack:g} mm: a "
                "blank that far off the stop puts the reamer into the plate"
            )
        values["hub_relief_x_mm"] = [hub_x - relief / 2, hub_x + relief / 2]
