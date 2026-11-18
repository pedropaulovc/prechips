"""Bindings for a fixture plate with an integral fence and end stop.

The plate is a flat bar length whose top is milled down round a fence along
its back edge and a stop at its left end. The model frame is the fixture's
own work zero: X0 the stop's face, Y0 the fence's face (the plate lies at
-Y, the fence at +Y), Z0 the milled plate top; the fence and stop tops stand
above Z0 and the underside lies below it. The fence is notched to the plate
top at both ends. Along the front, edge-clamp pockets each carry a tapped
hole; one counterbore with a tapped hole through its floor locates a plug.
"""

from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _blank_mm,
    _edge_breaks,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _required,
    _string,
)

_FIXED = (
    "plate_top",
    "faced_top",
    "underside",
    "fence_face",
    "stop_face",
    "front_edge",
    "back_edge",
    "left_end",
    "right_end",
    "fence_notch_left",
    "fence_notch_right",
    "hub_counterbore",
    "hub_tap",
)
_UP = [0, 0, 1]


def _feature(features: dict, name: str, kind: str) -> dict:
    item = features.get(name)
    if (
        not isinstance(item, dict)
        or item.get("kind") != kind
        or item.get("frame") != "model"
    ):
        raise CadError(f"{name}: expected a model-frame {kind}")
    return item


def _plane(features: dict, name: str, axis: str) -> tuple[dict, float]:
    """A face and where its plane lies along ``axis``."""
    face = _feature(features, name, "face")
    plane = face.get("plane")
    if not isinstance(plane, dict) or plane.get("axis") != axis:
        raise CadError(f"{name}.plane: expected a plane on {axis}")
    return face, _number(plane.get("value"), f"{name}.plane.value")


def _datum(features: dict, name: str, axis: str) -> None:
    if _plane(features, name, axis)[1] != 0:
        raise CadError(f"{name}: expected the {axis.upper()}0 datum face")


def _within(value: float, band: tuple[float, float], where: str) -> float:
    if not band[0] <= value <= band[1]:
        raise CadError(f"{where}: {value:g} mm lies outside its band")
    return value


def _hole(features: dict, name: str) -> tuple[dict, list[float]]:
    """A tapped through hole along Z and its model point."""
    hole = _feature(features, name, "hole")
    at = hole.get("at")
    if (
        hole.get("axis") != _UP
        or hole.get("thru") is not True
        or not isinstance(at, list)
        or len(at) != 3
    ):
        raise CadError(f"{name}: expected a through hole along Z")
    return hole, [_number(item, f"{name}.at") for item in at]


def _pockets(features: dict, values: dict) -> None:
    """Clamp pockets ``clamp_pocket_N`` from 1, each with its ``clamp_tap_N``."""
    count = sum(1 for name in features if name.startswith("clamp_pocket_"))
    names = [f"clamp_pocket_{number}" for number in range(1, count + 1)]
    taps = [f"clamp_tap_{number}" for number in range(1, count + 1)]
    if count < 1 or features.keys() != {*_FIXED, *names, *taps}:
        raise CadError(
            "cad.features: expected the plate's faces, both fence notches, the "
            "hub counterbore and tap, and clamp_pocket_N with clamp_tap_N from 1"
        )
    first = _feature(features, names[0], "profile")
    bands = {
        key: _band(first, key, names[0]) for key in ("back_wall_y", "length", "depth")
    }
    floor = _number(first.get("floor_z"), f"{names[0]}.floor_z")
    _within(-floor, bands["depth"], f"{names[0]}.floor_z")
    radius = _positive(first.get("corner_radius_max"), f"{names[0]}.corner_radius_max")
    # Both walls across the pocket, as positive distances from Y0: the near
    # one (toward the fence) and the back one, which carries the band.
    walls = first.get("y_walls")
    if not isinstance(walls, list) or len(walls) != 2:
        raise CadError(f"{names[0]}.y_walls: expected the pocket's two walls")
    back, near = (-_number(wall, f"{names[0]}.y_walls") for wall in walls)
    _within(back, bands["back_wall_y"], f"{names[0]}.y_walls")
    if not 0 < near < back:
        raise CadError(f"{names[0]}.y_walls: expected [back wall, near wall] at -Y")
    drill = thread = length = row = None
    stations = []
    for name, tap_name in zip(names, taps, strict=True):
        pocket = _feature(features, name, "profile")
        if (
            any(_band(pocket, key, name) != band for key, band in bands.items())
            or pocket.get("floor_z") != first["floor_z"]
            or pocket.get("corner_radius_max") != first["corner_radius_max"]
            or pocket.get("y_walls") != first.get("y_walls")
        ):
            raise CadError(f"{name}: the clamp pockets disagree")
        _required(pocket, "centre_x", name)
        centre = _positive(pocket.get("centre_x"), f"{name}.centre_x")
        if stations and centre <= stations[-1]:
            raise CadError(f"{name}.centre_x: expected ascending stations")
        if stations and centre - stations[-1] <= bands["length"][1]:
            raise CadError(f"{name}.centre_x: overlaps the pocket before it")
        stations.append(centre)
        tap, (x, y, z) = _hole(features, tap_name)
        found = (
            _positive(tap.get("drill_dia"), f"{tap_name}.drill_dia"),
            _string(tap.get("thread"), f"{tap_name}.thread"),
            _positive(tap.get("thread_length"), f"{tap_name}.thread_length"),
            -y,
        )
        if (drill, thread, length, row) not in ((None,) * 4, found):
            raise CadError(f"{tap_name}: the clamp taps disagree")
        drill, thread, length, row = found
        # The screw's hole sits on the pocket's centre, in its floor, whole
        # between its walls.
        if (
            x != centre
            or z != floor
            or not near < row - drill / 2
            or not row + drill / 2 < bands["back_wall_y"][0]
        ):
            raise CadError(f"{tap_name}.at: expected in the floor of {name}")
    for key, name in (
        ("back_wall_y", "pocket_back_wall"),
        ("length", "pocket_length"),
        ("depth", "pocket_depth"),
    ):
        _inch_limits(values, name, bands[key])
    values["pocket_count"] = count
    values["pocket_x_mm"] = stations
    values["pocket_stations_in"] = ", ".join(f"{x / 25.4:.2f}" for x in stations)
    values["pocket_floor_z_mm"] = floor
    values["pocket_width_mm"] = back - near
    values["pocket_near_wall_mm"] = near
    values["corner_radius_max_in"] = radius / 25.4
    values["clamp_thread"] = thread
    values["clamp_tap_drill_mm"] = drill
    values["clamp_thread_length_mm"] = length
    values["clamp_tap_y_mm"] = row


def _notches(features: dict, values: dict, ends: tuple[float, float]) -> None:
    """Both fence notches: cut to the plate top, from an inner end out to the
    plate's end (the left one from the stop's face)."""
    depths = []
    # (side, the plate edge the notch runs out to, which end of x that is)
    for side, outer, index in (("left", 0.0, 0), ("right", ends[1], 1)):
        name = f"fence_notch_{side}"
        notch = _feature(features, name, "profile")
        span = notch.get("x")
        _required(notch, "x", name)
        if not isinstance(span, list) or len(span) != 2:
            raise CadError(f"{name}.x: expected the notch's [start, end]")
        span = [_number(item, f"{name}.x") for item in span]
        if span[index] != outer or span[0] >= span[1] or notch.get("floor_z") != 0:
            raise CadError(
                f"{name}: expected a notch to the plate top running out to "
                f"X {outer:g} mm"
            )
        end = _band(notch, "end_x", name)
        _within(span[1 - index], end, f"{name}.x")
        _inch_limits(values, f"notch_{side}_end_x", end)
        values[f"notch_{side}_x_mm"] = span
        depths.append(_band(notch, "depth", name))
    if depths[0] != depths[1]:
        raise CadError("fence_notch_right.depth: the two notches disagree")
    _inch_limits(values, "notch_depth", depths[0])


def _hub(features: dict, values: dict) -> None:
    """The counterbore in the plate top and the tapped hole through its floor."""
    bore = _feature(features, "hub_counterbore", "counterbore")
    at = bore.get("at")
    _required(bore, "at", "hub_counterbore")
    if (
        bore.get("axis") != _UP
        or not isinstance(at, list)
        or len(at) != 3
        or at[2] != 0
    ):
        raise CadError("hub_counterbore: expected a counterbore in the plate top")
    x, y = (_number(item, "hub_counterbore.at") for item in at[:2])
    for key, nominal in (("x", x), ("y", -y)):
        band = _band(bore, key, "hub_counterbore")
        _within(nominal, band, f"hub_counterbore.{key}")
        _inch_limits(values, f"hub_{key}", band)
        values[f"hub_{key}_mm"] = nominal
    depth = _band(bore, "depth", "hub_counterbore")
    floor = _number(bore.get("floor_z"), "hub_counterbore.floor_z")
    _within(-floor, depth, "hub_counterbore.floor_z")
    _inch_limits(values, "counterbore_dia", _band(bore, "dia", "hub_counterbore"))
    _inch_limits(values, "counterbore_depth", depth)
    values["counterbore_floor_z_mm"] = floor
    tap, point = _hole(features, "hub_tap")
    if point != [x, y, floor]:
        raise CadError("hub_tap.at: expected at the centre of the counterbore's floor")
    values["hub_thread"] = _string(tap.get("thread"), "hub_tap.thread")
    values["hub_tap_drill_mm"] = _positive(tap.get("drill_dia"), "hub_tap.drill_dia")
    if values["hub_tap_drill_mm"] >= values["counterbore_dia_band_mm"][0]:
        raise CadError("hub_tap.drill_dia: no smaller than the counterbore")
    _required(tap, "engagement_min", "hub_tap")
    values["hub_engagement_min_mm"] = _positive(
        tap.get("engagement_min"), "hub_tap.engagement_min"
    )


def _placement(values: dict, ends: tuple[float, float], front: float) -> None:
    """Refuse pockets or a counterbore that leave the plate top or cut into
    each other, each taken at its largest."""
    half = values["pocket_length_band_mm"][1] / 2
    stations = values["pocket_x_mm"]
    if stations[0] - half <= 0 or stations[-1] + half >= ends[1]:
        raise CadError("cad.pocket_x_mm: a clamp pocket runs off the plate top")
    if values["pocket_back_wall_band_mm"][1] >= front:
        raise CadError("clamp_pocket_N.back_wall_y: beyond the front edge")
    radius = values["counterbore_dia_band_mm"][1] / 2
    x, y = values["hub_x_band_mm"], values["hub_y_band_mm"]
    if x[0] - radius <= 0 or x[1] + radius >= ends[1]:
        raise CadError("hub_counterbore.x: the counterbore runs off the plate top")
    if y[0] - radius <= 0 or y[1] + radius >= front:
        raise CadError(
            "hub_counterbore.y: the counterbore meets the fence or the front edge"
        )
    beside = all(
        x[1] + radius < station - half or x[0] - radius > station + half
        for station in stations
    )
    if not beside and y[1] + radius >= values["pocket_near_wall_mm"]:
        raise CadError("hub_counterbore: the counterbore cuts into a clamp pocket")


def load_fence_plate(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the plate's envelope, fence, notches, clamp pockets and hub."""
    raw, values, features = _read_manifest(path, part, "fence_plate")
    _model_frame(raw)
    for name, axis in (("plate_top", "z"), ("fence_face", "y"), ("stop_face", "x")):
        _datum(features, name, axis)

    # Thickness: underside (as received) to the faced fence and stop tops.
    top, fence_height = _plane(features, "faced_top", "z")
    height = _band(top, "height", "faced_top")
    _within(fence_height, height, "faced_top.plane")
    _inch_limits(values, "fence_height", height)
    values["fence_height_mm"] = fence_height
    under, low = _plane(features, "underside", "z")
    if low >= 0:
        raise CadError("underside: expected below the plate top")
    thickness = _band(under, "thickness", "underside")
    values["thickness_mm"] = _within(
        fence_height - low, thickness, "underside.thickness"
    )
    _inch_limits(values, "thickness", thickness)
    values["plate_top_height_mm"] = -low

    # Width: front edge to the fence's back; the fence is the part behind Y0.
    front, front_y = _plane(features, "front_edge", "y")
    back, back_y = _plane(features, "back_edge", "y")
    if not front_y < 0 < back_y:
        raise CadError("front_edge: expected the plate at -Y and the fence at +Y")
    width = _band(front, "width", "front_edge")
    values["width_mm"] = _within(back_y - front_y, width, "front_edge.width")
    _inch_limits(values, "width", width)
    fence = _band(back, "y", "back_edge")
    values["fence_width_mm"] = _within(back_y, fence, "back_edge.y")
    _inch_limits(values, "fence_width", fence)

    # Length: the stop stands between the left end and X0.
    right, right_x = _plane(features, "right_end", "x")
    ends = (_plane(features, "left_end", "x")[1], right_x)
    if not ends[0] < 0 < ends[1]:
        raise CadError("left_end: expected the stop's face between the plate's ends")
    length = _band(right, "length", "right_end")
    values["plate_x_mm"] = list(ends)
    values["length_mm"] = _within(ends[1] - ends[0], length, "right_end.length")
    _inch_limits(values, "length", length)
    values["stop_width_mm"] = -ends[0]

    _notches(features, values, ends)
    _pockets(features, values)
    _hub(features, values)
    _placement(values, ends, -front_y)
    # Stations from the plate's left end, for beams and cuts along the plate.
    stop = values["stop_width_mm"]
    values["pocket_beam_x_mm"] = [x + stop for x in values["pocket_x_mm"]]
    values["hub_beam_x_mm"] = values["hub_x_mm"] + stop
    for side in ("left", "right"):
        values[f"notch_{side}_beam_x_mm"] = [
            x + stop for x in values[f"notch_{side}_x_mm"]
        ]

    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["material_spec"] = _string(material.get("spec"), "cad.material.spec")
    values["material_name"] = _string(material.get("name"), "cad.material.name")
    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    envelope = tuple(
        StockAxis(key, f"blank_{key}_in", values[f"{key}_mm"])
        for key in ("length", "width", "thickness")
    )
    return CadData(values, StockRequirement("in", envelope), path.resolve())
