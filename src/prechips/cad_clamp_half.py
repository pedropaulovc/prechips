"""Bindings for one half of a split clamp block round a column.

Each half is a rectangular block with a half bore across its mating face;
the pair bolts together through two ears, one either side of the bore. The
front half's ears are clearance holes, the back half's are tapped. The pair
is bored together with the front's mating face on the bore axis; the back's
mating face is then faced back from the axis to leave a grip gap, so the
back is sized deeper than drawn before the bore.

Model frame: X across the split, the bore axis at X0 and the front half
toward +X; Y the height; Z the width, the near side at +Z; the bore axis
along Y. The front's outside face is its bar face, the back's its back face.
"""

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
    _plane,
    _positive,
    _read_manifest,
    _string,
    inch_thread,
)

_SHARED = {"mating_face", "bottom_face", "top_face", "near_side", "far_side", "bore"}
# Per half: its outside face, its two ears and their kind, and +1 when the
# outside face lies toward +X.
_HALVES = {
    "front": ("bar_face", ("ear_hole_1", "ear_hole_2"), "hole", 1),
    "back": ("back_face", ("ear_tap_1", "ear_tap_2"), "threaded_hole", -1),
}
_BLANK = ("blank_length_min_in", "blank_length_max_in")
_OTHER = ("other_half_depth_min_mm", "other_half_depth_max_mm")
_TOLERANCE = 1e-6


def _thread_major(thread: str, where: str) -> float:
    """An internal numbered thread's basic major diameter, mm: the least
    diameter its crests reach."""
    major, _tpi, numbered = inch_thread(thread, where)
    if not numbered:
        raise CadError(f"{where}: expected a numbered internal thread, #N-TPI UNC-2B")
    return major


def _close(found: float, expected: float) -> bool:
    return abs(found - expected) <= _TOLERANCE


def _inside(value: float, band: tuple[float, float], where: str) -> float:
    if not band[0] - _TOLERANCE <= value <= band[1] + _TOLERANCE:
        raise CadError(f"{where}: {value:g} mm lies outside its band")
    return value


def _which(features: dict) -> str:
    for half, (outside, ears, _kind, _sign) in _HALVES.items():
        if features.keys() == _SHARED | {outside, *ears}:
            return half
    expected = (
        f"{', '.join(sorted(_SHARED | {outside, *ears}))} ({half})"
        for half, (outside, ears, _kind, _sign) in _HALVES.items()
    )
    raise CadError(f"cad.features: expected exactly {' or '.join(expected)}")


def _height(features: dict, values: dict) -> float:
    """Height between the bottom and top faces; returns the bottom's Y."""
    bottom, low = _plane(features, "bottom_face", "y")
    top, high = _plane(features, "top_face", "y")
    band = _band(bottom, "height", "bottom_face")
    nominal = _positive(bottom.get("height_nominal"), "bottom_face.height_nominal")
    if (
        _band(top, "height", "top_face") != band
        or top.get("height_nominal") != nominal
        or not _close(high - low, nominal)
    ):
        raise CadError("top_face: expected the height band from bottom_face")
    _inside(nominal, band, "bottom_face.height_nominal")
    _inch_limits(values, "height", band)
    values["height_mm"] = nominal
    return low


def _width(features: dict, values: dict) -> float:
    """Width from the near side to the far side; returns the near side's Z."""
    _near, near = _plane(features, "near_side", "z")
    far, far_z = _plane(features, "far_side", "z")
    band = _band(far, "width", "far_side")
    nominal = _positive(far.get("width_nominal"), "far_side.width_nominal")
    if far.get("width_from") != "near_side" or not _close(near - far_z, nominal):
        raise CadError("far_side: expected the width band from near_side")
    _inside(nominal, band, "far_side.width_nominal")
    _inch_limits(values, "width", band)
    values["width_mm"] = nominal
    return near


def _depth(features: dict, values: dict, half: str) -> float:
    """Depth from the mating face to the outside face; returns the outside
    face's distance from the bore axis."""
    outside, _ears, _kind, sign = _HALVES[half]
    mating, mate_x = _plane(features, "mating_face", "x")
    face, out_x = _plane(features, outside, "x")
    band = _band(face, "depth", outside)
    nominal = _positive(face.get("depth_nominal"), f"{outside}.depth_nominal")
    if face.get("depth_from") != "mating_face" or not _close(
        sign * (out_x - mate_x), nominal
    ):
        raise CadError(f"{outside}: expected the depth band from mating_face")
    _inside(nominal, band, f"{outside}.depth_nominal")
    _inch_limits(values, "depth", band)
    values["depth_mm"] = nominal
    if half == "front":
        if mate_x != 0:
            raise CadError("mating_face: expected on the bore axis, X0")
        _inch_limits(values, "bore_axis_depth", band)
    else:
        # The back's mating face is faced back from the axis after the bore.
        offset = _band(mating, "grip_offset", "mating_face")
        gap = _positive(
            mating.get("grip_offset_nominal"), "mating_face.grip_offset_nominal"
        )
        if mating.get("grip_offset_from") != "bore" or not _close(-mate_x, gap):
            raise CadError("mating_face: expected the grip offset behind the bore axis")
        _inside(gap, offset, "mating_face.grip_offset_nominal")
        _inch_limits(values, "grip_offset", offset)
        values["grip_offset_mm"] = gap
        # Sized before the bore with its mating face on the axis: facing the
        # nominal gap off then leaves the drawn depth.
        before = (band[0] + gap, band[1] + gap)
        _inch_limits(values, "pre_face_depth", before)
        values["pre_face_depth_mm"] = -out_x
        _inch_limits(values, "bore_axis_depth", before)
    values["bore_axis_depth_mm"] = sign * out_x
    return sign * out_x


def _bore(features: dict, values: dict, near: float) -> float:
    """The half bore across the mating face; returns its largest radius."""
    bore = _feature(features, "bore", "half_bore")
    if (
        bore.get("at") != [0, 0, 0]
        or bore.get("axis") != [0, 1, 0]
        or bore.get("thru") is not True
        or bore.get("open_to") != "mating_face"
    ):
        raise CadError(
            "bore: expected a half bore through the height on the model axis, "
            "open to mating_face"
        )
    column = _positive(bore.get("mate_od_nominal"), "bore.mate_od_nominal")
    clearance = _band(bore, "diametral_clearance", "bore")
    dia = (column + clearance[0], column + clearance[1])
    ref = _inside(_positive(bore.get("dia_ref"), "bore.dia_ref"), dia, "bore.dia_ref")
    _inch_limits(values, "bore_dia", dia)
    values["bore_dia_mm"] = ref
    values["column_dia_mm"] = column
    values["column_dia_in"] = column / 25.4
    values["bore_clearance_min_in"] = clearance[0] / 25.4
    values["bore_clearance_max_in"] = clearance[1] / 25.4
    location = _band(bore, "location_from_near_side", "bore")
    nominal = _positive(bore.get("location_nominal"), "bore.location_nominal")
    if bore.get("location_from") != "near_side" or not _close(near, nominal):
        raise CadError("bore: expected its location from near_side")
    _inside(nominal, location, "bore.location_nominal")
    _inch_limits(values, "bore_location", location)
    values["bore_location_mm"] = nominal
    values["bore_from_far_mm"] = values["width_mm"] - nominal
    values["bore_from_far_in"] = values["bore_from_far_mm"] / 25.4
    radius = dia[1] / 2
    # Least wall at the band extremes: behind the bore, and to each side.
    walls = {
        "the outside face": values["bore_axis_depth_band_mm"][0] - radius,
        "the near side": location[0] - radius,
        "the far side": values["width_band_mm"][0] - location[1] - radius,
    }
    for where, wall in walls.items():
        if wall <= 0:
            raise CadError(
                f"bore: Ø{dia[1]:g} mm at its band extremes breaks through {where}"
            )
    values["bore_wall_worst_mm"] = walls["the outside face"]
    values["bore_wall_worst_in"] = walls["the outside face"] / 25.4
    return radius


def _ears(
    features: dict, values: dict, half: str, near: float, bottom: float, radius: float
) -> None:
    """The two ears, mirrored about the bore axis, through the depth."""
    outside, names, kind, sign = _HALVES[half]
    ears = [_feature(features, name, kind) for name in names]
    out_x = sign * values["bore_axis_depth_mm"]
    stations = [_band(ear, "station", name) for ear, name in zip(ears, names)]
    first = stations[0]
    if first[0] <= 0 or stations[1] != (-first[1], -first[0]):
        raise CadError(
            f"{names[1]}.station: expected the mirror of {names[0]} about the bore"
        )
    dia = _band(ears[0], "dia", names[0])
    height = _band(ears[0], "height", names[0])
    nominal = _positive(ears[0].get("station_nominal"), f"{names[0]}.station_nominal")
    _inside(nominal, first, f"{names[0]}.station_nominal")
    rise = _positive(ears[0].get("height_nominal"), f"{names[0]}.height_nominal")
    _inside(rise, height, f"{names[0]}.height_nominal")
    for ear, name, side in zip(ears, names, (1, -1)):
        at = ear.get("at")
        if (
            not isinstance(at, list)
            or len(at) != 3
            or ear.get("axis") != [-sign, 0, 0]
            or ear.get("thru") is not True
            or "thru" not in ear.get("requirements", [])
            or ear.get("station_from") != "bore"
            or ear.get("height_from") != "bottom_face"
        ):
            raise CadError(
                f"{name}: expected a through hole across the depth from "
                f"{outside}, its station from the bore and height from bottom_face"
            )
        if (
            _band(ear, "dia", name) != dia
            or _band(ear, "height", name) != height
            or ear.get("station_nominal") != side * nominal
            or ear.get("height_nominal") != rise
        ):
            raise CadError(f"{name}: disagrees with {names[0]}")
        x, y, z = (_number(item, f"{name}.at") for item in at)
        if not (
            _close(x, out_x) and _close(y - bottom, rise) and _close(z, side * nominal)
        ):
            raise CadError(
                f"{name}.at: expected on {outside} at its station and height"
            )
    _inch_limits(values, "ear_dia", dia)
    _inch_limits(values, "ear_station", first)
    _inch_limits(values, "ear_height", height)
    values["ear_station_mm"] = nominal
    values["ear_height_mm"] = rise
    # Common-zero coordinates: from the near side, from the bore axis, and up
    # from the bottom face; each ear is drilled through the depth the half has
    # then (the back's before its face-off). Drilled before the bore, an ear's
    # X from the near side carries the station band about the bore's nominal
    # location (the bore is then interpolated at that location).
    _inch_limits(values, "ear_near_x", (near - first[1], near - first[0]))
    _inch_limits(values, "ear_far_x", (near + first[0], near + first[1]))
    for key, value in (
        ("ear_near_x", near - nominal),
        ("ear_far_x", near + nominal),
        ("ear_offset_x", nominal),
        ("ear_y", rise),
        ("ear_depth", values["bore_axis_depth_mm"]),
    ):
        values[f"{key}_mm"] = value
        values[f"{key}_in"] = value / 25.4
    if half == "front":
        lowest = {
            _number(ear.get("web_to_bore_min"), f"{name}.web_to_bore_min")
            for ear, name in zip(ears, names)
        }
        clearance = {ear.get("clearance_for") for ear in ears}
        if len(lowest) != 1 or len(clearance) != 1:
            raise CadError(f"{names[1]}: disagrees with {names[0]}")
        values["ear_clearance_for"] = _string(
            ears[0].get("clearance_for"), f"{names[0]}.clearance_for"
        )
        wall_min = _positive(lowest.pop(), f"{names[0]}.web_to_bore_min")
        values["ear_wall_min_mm"] = wall_min
        values["ear_wall_min_in"] = wall_min / 25.4
        # A drilled hole's edge is its diameter band.
        smallest, largest = dia
    else:
        threads = {ear.get("thread") for ear in ears}
        if len(threads) != 1:
            raise CadError(f"{names[1]}.thread: disagrees with {names[0]}")
        thread = _string(ears[0].get("thread"), f"{names[0]}.thread")
        values["ear_thread"] = thread
        wall_min = 0.0
        # A tapped hole's edge is its thread's major diameter, not the drill.
        smallest = largest = _thread_major(thread, f"{names[0]}.thread")
        values["ear_thread_major_mm"] = largest
    # Least walls at the band extremes: to the bore, to the bottom or top
    # face and to the nearer end.
    wall = first[0] - largest / 2 - radius
    if wall < wall_min - _TOLERANCE or wall <= 0:
        raise CadError(
            f"{names[0]}: at station {first[0]:g} mm a Ø{largest:g} mm hole leaves "
            f"{wall:.3f} mm to a Ø{2 * radius:g} mm bore, under the "
            f"{wall_min:g} mm least ear wall"
        )
    values["ear_wall_worst_mm"] = wall
    values["ear_wall_worst_in"] = wall / 25.4
    # The greatest wall, at the other extremes: the band the wall is gauged to.
    best = first[1] - smallest / 2 - values["bore_dia_band_mm"][0] / 2
    values["ear_wall_best_mm"] = best
    values["ear_wall_best_in"] = best / 25.4
    tall = values["height_band_mm"]
    edge = min(height[0], tall[0] - height[1]) - largest / 2
    location = values["bore_location_band_mm"]
    end = (
        min(location[0], values["width_band_mm"][0] - location[1])
        - first[1]
        - largest / 2
    )
    for where, worst in (("the bottom or top face", edge), ("an end", end)):
        if worst <= 0:
            raise CadError(f"{names[0]}: breaks through {where} at its band extremes")
    values["ear_edge_wall_worst_mm"] = edge
    values["ear_edge_wall_worst_in"] = edge / 25.4
    values["ear_end_wall_worst_in"] = end / 25.4


def _optional(parameters: dict, key: str) -> float | None:
    if key not in parameters:
        return None
    return _positive(parameters[key], f"process.{key}")


def _holds(values: dict, parameters: dict, half: str, radius: float) -> None:
    """The authored holds: the half lying on parallels for its ears, and the
    pair screwed together for the bore. Each check runs once its parameters
    are authored."""
    thick = _optional(parameters, "parallel_thickness_mm")
    edge = values["ear_edge_wall_worst_mm"]
    if thick is not None and thick >= edge:
        raise CadError(
            f"process.parallel_thickness_mm: {thick:g} mm parallels against the "
            f"jaws reach the ear holes, which come as near as {edge:.3f} mm to the "
            "bottom and top faces"
        )
    if not _all_or_none(parameters, _OTHER, "the other half's bored depth"):
        return
    # The pair across the split, each half's outside face to the bore axis:
    # this half's band from its manifest, the other half's as authored.
    other = tuple(_positive(parameters[key], f"process.{key}") for key in _OTHER)
    if other[0] > other[1]:
        raise CadError("process.other_half_depth_min_mm: over other_half_depth_max_mm")
    own = tuple(values["bore_axis_depth_band_mm"])
    front, back = (own, other) if half == "front" else (other, own)
    pair = (front[0] + back[0], front[1] + back[1])
    for key, band in (
        ("pair_depth", pair),
        ("pair_front_depth", front),
        ("pair_back_depth", back),
    ):
        _inch_limits(values, key, band)
        values[f"{key}_mm"] = values[f"{key}_in"] * 25.4
    length = _optional(parameters, "screw_length_mm")
    if length is not None:
        if length >= pair[0]:
            raise CadError(
                f"process.screw_length_mm: a {length:g} mm screw reaches the back "
                f"face of the thinnest pair, {pair[0]:.3f} mm"
            )
        values["screw_short_mm"] = pair[0] - length
        values["screw_short_in"] = (pair[0] - length) / 25.4
    block = _optional(parameters, "spacer_block_width_mm")
    head = _optional(parameters, "screw_head_dia_mm")
    if (block is None) != (head is None):
        raise CadError(
            "process: the spacer block between the screw heads needs both "
            "spacer_block_width_mm and screw_head_dia_mm"
        )
    if block is not None and head is not None:
        clear = values["ear_station_band_mm"][0] - head / 2 - block / 2
        if clear <= 0:
            raise CadError(
                f"process.spacer_block_width_mm: a {block:g} mm block centred on "
                f"the bore reaches the Ø{head:g} mm screw heads"
            )
        values["block_head_clear_mm"] = clear
        values["block_head_clear_in"] = clear / 25.4
    if thick is None:
        return
    # Parallels against the jaws under the pair stop short of the bore, at
    # each half's least depth: the front's along its whole band, the back's
    # only clear of the bore's end.
    walls = {"front": front[0] - radius, "back": back[0] - radius}
    if thick >= walls["front"]:
        raise CadError(
            f"process.parallel_thickness_mm: a {thick:g} mm parallel against the "
            f"front's outside face reaches the bore, {walls['front']:.3f} mm in"
        )
    end = _optional(parameters, "back_parallel_end_mm")
    if end is None:
        if thick >= walls["back"]:
            raise CadError(
                f"process.parallel_thickness_mm: a {thick:g} mm parallel along "
                f"the back's outside face reaches the bore, {walls['back']:.3f} mm "
                "in; stop it short with back_parallel_end_mm"
            )
        return
    near = values["bore_location_band_mm"][0]
    if not radius < end < near:
        raise CadError(
            f"process.back_parallel_end_mm: a parallel ending {end:g} mm from the "
            f"bore axis must clear the Ø{2 * radius:g} mm bore and still reach "
            f"under the back, whose near side is as near as {near:g} mm"
        )
    values["back_parallel_clear_mm"] = end - radius
    values["back_parallel_clear_in"] = (end - radius) / 25.4


def load_clamp_half(path: Path, parameters: dict, part: str) -> CadData:
    """Bind either half's envelope, bore, ears and, from authored parameters,
    its blank and the bolted pair across the split."""
    raw, values, features = _read_manifest(path, part, "clamp_half")
    _model_frame(raw)
    half = _which(features)
    values["half"] = half
    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["material_spec"] = _string(material.get("spec"), "cad.material.spec")
    values["finish"] = _string(material.get("finish"), "cad.material.finish")
    bottom = _height(features, values)
    near = _width(features, values)
    axis_depth = _depth(features, values, half)
    radius = _bore(features, values, near)
    if half == "back":
        # Clamped on the column the halves stand apart by the grip offset less
        # the diametral clearance: the least offset must exceed the most
        # clearance, or the mating faces meet before the bore grips.
        clearance = values["bore_clearance_max_in"] * 25.4
        if values["grip_offset_band_mm"][0] <= clearance + _TOLERANCE:
            raise CadError(
                f"mating_face.grip_offset: {values['grip_offset_band_mm'][0]:g} mm "
                f"at least does not exceed the bore's {clearance:g} mm diametral "
                "clearance: the halves would close before gripping the column"
            )
    _ears(features, values, half, near, bottom, radius)
    _edge_breaks(raw, values)
    if _all_or_none(parameters, _BLANK, "the sawn blank"):
        low, high = (_positive(parameters[key], f"process.{key}") for key in _BLANK)
        if low > high:
            raise CadError("process.blank_length_min_in: over blank_length_max_in")
        if low < values["width_max_in"] - _TOLERANCE:
            raise CadError(
                "process.blank_length_min_in: shorter than the widest finished half"
            )
        values["blank_length_min_mm"] = low * 25.4
        values["blank_length_max_mm"] = high * 25.4
        # Stock to come off the two ends together.
        values["end_stock_min_in"] = low - values["width_max_in"]
        values["end_stock_max_in"] = high - values["width_min_in"]
    if "blank_section_in" in parameters:
        section = _positive(parameters["blank_section_in"], "process.blank_section_in")
        # The bar must cover the half's largest height and bored depth.
        for name, band in (
            ("height", values["height_band_mm"]),
            ("bored depth", values["bore_axis_depth_band_mm"]),
        ):
            if section * 25.4 < band[1] - _TOLERANCE:
                raise CadError(
                    f"process.blank_section_in: under the largest {name}, "
                    f"{band[1] / 25.4:.3f} in"
                )
        values["blank_section_mm"] = section * 25.4
        values["section_stock_height_in"] = section - values["height_mm"] / 25.4
        values["section_stock_depth_in"] = section - axis_depth / 25.4
    _holds(values, parameters, half, radius)
    envelope = (
        StockAxis("length", "blank_length_min_in", values["width_mm"]),
        StockAxis("height", "blank_section_in", values["height_mm"]),
        StockAxis("depth", "blank_section_in", axis_depth),
    )
    return CadData(values, StockRequirement("in", envelope), path.resolve())
