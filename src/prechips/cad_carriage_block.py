"""Bindings for the harmonic oblique-trammel carriage blocks: the pivot block
(MHA-CH-06-TL-22) and the feed block (MHA-CH-06-TL-32).

Both blocks share one 1.64 × .96 section, the flat-floored pivot seat with its
tapped through hole and four counterbored carriage holes; the feed block adds
an integral nut lug with the leadscrew bore and four nut taps transferred at
assembly. One loader binds both, refusing any other shape.
"""

import math
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _blank_mm,
    _edge_breaks,
    _harmonic_manifest,
    _inch_limits,
    _model_frame,
    _number,
    _positive,
    _string,
)

# part: (adapter, Y-extent field on carriage_seat, plan row origin)
_PARTS = {
    "ch-rocker-arm-tl-oblique-pivot-block": (
        "harmonic_pivot_block",
        "width",
        "minus_y_side",
    ),
    "ch-rocker-arm-tl-oblique-feed-block": (
        "harmonic_feed_block",
        "overall_y",
        "plus_y_side",
    ),
}
_COMMON = {
    "carriage_seat",
    "pivot_bore",
    "pivot_tap",
    *(f"carriage_hole_{n}" for n in range(1, 5)),
    *(f"carriage_counterbore_{n}" for n in range(1, 5)),
}
_FEED = {"leadscrew_bore", *(f"nut_tap_{n}" for n in range(1, 5))}
_SEAT = {
    "harmonic_pivot_block": ["length", "width", "height"],
    "harmonic_feed_block": ["length", "height", "lug_x", "overall_y", "lug_length"],
}
_TOL_MM = 1e-6


def load_pivot_block(path: Path, parameters: dict) -> CadData:
    """Bind the pivot block (MHA-CH-06-TL-22)."""
    return _load(path, parameters, "ch-rocker-arm-tl-oblique-pivot-block")


def load_feed_block(path: Path, parameters: dict) -> CadData:
    """Bind the feed block (MHA-CH-06-TL-32)."""
    return _load(path, parameters, "ch-rocker-arm-tl-oblique-feed-block")


def _close(a: float, b: float, tol: float = _TOL_MM) -> bool:
    return math.isclose(a, b, abs_tol=tol)


def _printed_mm(item: dict, field: str, where: str) -> float:
    """Half a last printed inch digit of ``field``, in mm: how far the model
    point may sit from the nominal the sheet prints."""
    precision = item.get("precision")
    places = precision.get(field) if isinstance(precision, dict) else None
    if type(places) is not int or places < 0:
        raise CadError(f"{where}.precision.{field}: expected printed decimal places")
    return 0.5 * 10.0**-places * 25.4 + _TOL_MM


def _feature(features: dict, name: str, kind: str, requirements: list[str]) -> dict:
    item = features[name]
    if (
        not isinstance(item, dict)
        or item.get("frame") != "model"
        or item.get("kind") != kind
    ):
        raise CadError(f"cad.features.{name}: expected a model-frame {kind}")
    if item.get("requirements") != requirements:
        raise CadError(f"{name}.requirements: expected {', '.join(requirements)}")
    return item


def _nominal(item: dict, field: str, where: str) -> float:
    band = _band(item, field, where)
    value = _number(item.get(f"{field}_nominal"), f"{where}.{field}_nominal")
    if not band[0] - _TOL_MM <= value <= band[1] + _TOL_MM:
        raise CadError(f"{where}.{field}_nominal: outside the {field} band")
    return value


def _bind(values: dict, item: dict, field: str, where: str, key: str) -> float:
    _inch_limits(values, key, _band(item, field, where))
    value = _nominal(item, field, where)
    values[f"{key}_mm"] = value
    values[f"{key}_nominal_in"] = value / 25.4
    return value


def _half_band(band: tuple[float, float], value: float, where: str) -> float:
    """The ± a symmetric band prints about its nominal, in mm."""
    if not _close(band[1] - value, value - band[0]):
        raise CadError(f"{where}: expected a band symmetric about its nominal")
    return (band[1] - band[0]) / 2


def _hole(features: dict, name: str, requirements: list[str], axis: list) -> tuple:
    item = _feature(features, name, "hole", requirements)
    at = item.get("at")
    if (
        item.get("axis") != axis
        or not isinstance(at, list)
        or len(at) != 3
        or item.get("thru", True) is not True
    ):
        raise CadError(f"{name}: expected a hole along {axis}")
    return item, [_number(v, f"{name}.at") for v in at]


def _load(path: Path, parameters: dict, part: str) -> CadData:
    adapter, y_field, row_from = _PARTS[part]
    raw, values, features = _harmonic_manifest(path, part, adapter)
    _model_frame(raw)
    feed = adapter == "harmonic_feed_block"
    expected = _COMMON | (_FEED if feed else set())
    if set(features) != expected:
        raise CadError(f"cad.features: expected exactly {', '.join(sorted(expected))}")

    # Model X runs along the 1.64 length (stations from the -X end), Y across
    # (rows from the -Y side on TL-22, the +Y side on TL-32), Z up from the
    # carriage seat (Z0, facing -Z) to the top face.
    seat = _feature(features, "carriage_seat", "face", _SEAT[adapter])
    plane = seat.get("plane")
    if seat.get("normal") != [0, 0, -1] or plane != {
        "frame": "model",
        "axis": "z",
        "value": 0,
    }:
        raise CadError("carriage_seat: expected the Z0 carriage seat facing -Z")
    length = _bind(values, seat, "length", "carriage_seat", "length")
    y_length = _bind(values, seat, y_field, "carriage_seat", y_field)
    height = _bind(values, seat, "height", "carriage_seat", "height")
    _inch_limits(values, "y_length", _band(seat, y_field, "carriage_seat"))
    values["y_length_mm"] = y_length
    # The pictures put ROW SIDE on the hand the model frame gives it.
    values["row_from"] = row_from
    x_end = -length / 2
    envelope = (
        StockAxis("length", "blank_length_in", y_length),
        StockAxis("width", "blank_width_in", length),
        StockAxis("thickness", "blank_thickness_in", height),
    )

    def plan_position(item: dict, at: list, name: str) -> tuple[float, float, float]:
        """Return the station, the hole's model Y origin edge and how far that
        edge may sit off the true one from the printed row's rounding."""
        if (
            item.get("station_from") != "minus_x_end"
            or item.get("row_from") != row_from
        ):
            raise CadError(f"{name}: expected stations from -X, rows from {row_from}")
        station = _nominal(item, "station", name)
        row = _nominal(item, "row", name)
        if not _close(at[2], height):
            raise CadError(f"{name}.at: expected entry at TOP (height)")
        if not _close(at[0] - x_end, station, _printed_mm(item, "station", name)):
            raise CadError(f"{name}.at: station disagrees with the -X end")
        edge = at[1] - row if row_from == "minus_y_side" else at[1] + row
        return station, edge, _printed_mm(item, "row", name)

    # Pivot seat: flat-floored .375 down from the top, tap through below it.
    bore, bore_at = _hole(
        features, "pivot_bore", ["dia", "depth", "station", "row"], [0, 0, -1]
    )
    if bore.get("floor") != "flat" or "thru" in bore:
        raise CadError("pivot_bore: expected a flat-floored blind bore")
    bore_station, y_edge, edge_tol = plan_position(bore, bore_at, "pivot_bore")
    _bind(values, bore, "dia", "pivot_bore", "bore_dia")
    _bind(values, bore, "depth", "pivot_bore", "bore_depth")
    for field, key in (("station", "bore_x"), ("row", "bore_y")):
        value = _bind(values, bore, field, "pivot_bore", key)
        half = _half_band(
            _band(bore, field, "pivot_bore"), value, f"pivot_bore.{field}"
        )
        values[f"{key}_tol_in"] = half / 25.4
    tap, tap_at = _hole(features, "pivot_tap", ["thread", "dia", "thru"], [0, 0, -1])
    if (
        tap.get("thru") is not True
        or tap.get("parent") != "pivot_bore"
        or tap_at != bore_at
    ):
        raise CadError("pivot_tap: expected a through tap on the pivot bore axis")
    values["pivot_thread"] = _string(tap.get("thread"), "pivot_tap.thread")
    _inch_limits(values, "tap_drill", _band(tap, "dia", "pivot_tap"))
    values["tap_drill_mm"] = _positive(
        tap.get("tap_drill_mm"), "pivot_tap.tap_drill_mm"
    )

    # Carriage holes: two stations by two rows, each counterbored from the top.
    shared: dict = {}
    points = []
    # Each hole's worst case toward the notch: least station, greatest row.
    extremes = []
    # The holes' own row origin (from the first), held to their printed places.
    hole_edge = None
    for n in range(1, 5):
        name = f"carriage_hole_{n}"
        cbore_name = f"carriage_counterbore_{n}"
        item, at = _hole(features, name, ["dia", "thru", "station", "row"], [0, 0, -1])
        if item.get("thru") is not True:
            raise CadError(f"{name}: expected a through hole")
        station, edge, tol = plan_position(item, at, name)
        # The bore prints coarser: its looser tolerance only relates it to the
        # holes; the holes agree with each other at their own precision.
        if not _close(edge, y_edge, edge_tol + tol):
            raise CadError(f"{name}.at: row origin disagrees with the pivot bore")
        if hole_edge is None:
            hole_edge = (edge, tol)
        elif not _close(edge, hole_edge[0], hole_edge[1] + tol):
            raise CadError(f"{name}.at: row origin disagrees with carriage_hole_1")
        cbore = _feature(features, cbore_name, "counterbore", ["dia", "floor"])
        if cbore.get("parent") != name or cbore.get("floor_from") != "carriage_seat":
            raise CadError(f"{cbore_name}: expected {name}'s counterbore")
        for key, source, where, field in (
            ("hole_dia", item, name, "dia"),
            ("cbore_dia", cbore, cbore_name, "dia"),
            ("cbore_floor", cbore, cbore_name, "floor"),
            ("station", item, name, "station"),
            ("row", item, name, "row"),
        ):
            band = (_band(source, field, where), _nominal(source, field, where))
            if key in ("station", "row"):
                shared.setdefault(key, set()).add(band)
            elif shared.setdefault(key, band) != band:
                raise CadError(f"{where}.{field}: carriage holes disagree")
        depth_ref = _positive(cbore.get("depth_ref"), f"{cbore_name}.depth_ref")
        if not _close(depth_ref, height - shared["cbore_floor"][1]):
            raise CadError(f"{cbore_name}.depth_ref: not height − floor")
        points.append((station, _nominal(item, "row", name)))
        extremes.append((_band(item, "station", name)[0], _band(item, "row", name)[1]))
    for key in ("hole_dia", "cbore_dia", "cbore_floor"):
        band, value = shared[key]
        _inch_limits(values, key, band)
        values[f"{key}_mm"] = value
        values[f"{key}_nominal_in"] = value / 25.4
    values["cbore_depth_in"] = depth_ref / 25.4
    # Stations (model X, hole_x*) and rows (model Y, hole_y*) each print one ±
    # for every hole: both bands of each must share it.
    for key, axis in (("station", "x"), ("row", "y")):
        if len(shared[key]) != 2:
            raise CadError(f"carriage holes: expected two {key} bands")
        halves = set()
        for index, (band, value) in enumerate(sorted(shared[key], key=lambda b: b[1])):
            label = f"hole_{axis}{index + 1}"
            _inch_limits(values, label, band)
            values[f"{label}_mm"] = value
            values[f"{label}_nominal_in"] = value / 25.4
            halves.add(round(_half_band(band, value, f"carriage holes.{key}"), 6))
        if len(halves) != 1:
            raise CadError(f"carriage holes: the two {key} bands differ in width")
        values[f"hole_{axis}_tol_in"] = halves.pop() / 25.4
    if sorted(points) != sorted(
        (x, y)
        for x in (values["hole_x1_mm"], values["hole_x2_mm"])
        for y in (values["hole_y1_mm"], values["hole_y2_mm"])
    ):
        raise CadError("carriage holes: expected a two-by-two pattern")
    values["hole_count"] = 4
    values["hole_rows"] = [
        ["B", f"{values['bore_y_nominal_in']:.3f}", f"{bore_station / 25.4:.3f}"],
        *(
            [f"H{index}", f"{y / 25.4:.3f}", f"{x / 25.4:.3f}"]
            for index, (x, y) in enumerate(
                sorted(points, key=lambda p: (p[0], p[1])), 1
            )
        ),
    ]

    if feed:
        _feed(
            features,
            values,
            parameters,
            seat=seat,
            y_edge=y_edge,
            edge_tol=edge_tol,
            holes=[
                (
                    values["bore_x_band_mm"][0],
                    values["bore_y_band_mm"][1],
                    values["bore_dia_band_mm"][1] / 2,
                ),
                *((x, y, values["cbore_dia_band_mm"][1] / 2) for x, y in extremes),
            ],
        )
    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    # A centred vise hold leaves equal insets (negative overhangs) at both jaw
    # sides: (span along the jaws − jaw width) / 2, for each span a hold uses.
    if "vise_jaw_width_mm" in parameters:
        jaw = _positive(parameters["vise_jaw_width_mm"], "process.vise_jaw_width_mm")
        for key, along in (
            ("blank", values.get("blank_length_mm")),
            ("offcut", values.get("offcut_length_mm")),
            ("x", length),
            ("y", y_length),
        ):
            if along is not None:
                values[f"centred_overhang_{key}_mm"] = (along - jaw) / 2
    return CadData(values, StockRequirement("in", envelope), path.resolve())


def _feed(
    features: dict,
    values: dict,
    parameters: dict,
    *,
    seat: dict,
    y_edge: float,
    edge_tol: float,
    holes: list[tuple[float, float, float]],
) -> None:
    """Bind the feed block's lug, leadscrew clearance and assembly-transferred
    taps, and the plan's lug-relative process values.

    ``holes`` are the top holes as (least station, greatest row, greatest
    radius) in mm, the counterbores' for H1–H4; each must stay clear of the
    notch at its band extremes.
    """
    lug_x = _bind(values, seat, "lug_x", "carriage_seat", "lug_x")
    lug_length = _bind(values, seat, "lug_length", "carriage_seat", "lug_length")
    length, height, overall_y = (
        values["length_mm"],
        values["height_mm"],
        values["overall_y_mm"],
    )
    if not (
        values["lug_x_max_in"] < values["length_min_in"]
        and values["lug_length_max_in"] < values["overall_y_min_in"]
    ):
        raise CadError("carriage_seat: expected the lug inside the block's length")
    # The notch takes SPINDLE END to lug_x, from LUG END to lug_length; the
    # head beyond it, overall_y − lug_length from ROW SIDE, keeps every hole,
    # taken at the smallest head and the deepest notch the bands allow.
    head = values["overall_y_band_mm"][0] - values["lug_length_band_mm"][1]
    notch_x = values["lug_x_band_mm"][1]
    for station, row, radius in holes:
        if row + radius > head and station - radius < notch_x:
            raise CadError("carriage_seat: a top hole breaks into the lug notch")
    values["lug_width_mm"] = length - lug_x
    lug_end = y_edge - overall_y
    # A plain through hole under the title block (no process word on the sheet).
    bore, at = _hole(
        features, "leadscrew_bore", ["dia", "thru", "row", "height"], [-1, 0, 0]
    )
    if (
        bore.get("thru") is not True
        or "process" in bore
        or bore.get("row_from") != "lug_end"
        or bore.get("height_from") != "carriage_seat"
    ):
        raise CadError("leadscrew_bore: expected a plain through hole from the lug end")
    row = _bind(values, bore, "row", "leadscrew_bore", "screw_y")
    z = _bind(values, bore, "height", "leadscrew_bore", "screw_z")
    # LUG END comes from the pivot row and the overall length, both printed
    # nominals: allow each one's rounding as well as the bore row's own.
    row_tol = (
        edge_tol
        + _printed_mm(seat, "overall_y", "carriage_seat")
        + _printed_mm(bore, "row", "leadscrew_bore")
    )
    if (
        not _close(at[0], length / 2, _printed_mm(seat, "length", "carriage_seat"))
        or not _close(at[1] - lug_end, row, row_tol)
        or not _close(at[2], z, _printed_mm(bore, "height", "leadscrew_bore"))
        or row >= lug_length
        or not 0 < z < height
    ):
        raise CadError("leadscrew_bore.at: expected on the lug, from its +X face")
    _bind(values, bore, "dia", "leadscrew_bore", "screw_dia")
    values["screw_z_band_text"] = (
        f"{values['screw_z_band_mm'][0]:.2f}–{values['screw_z_band_mm'][1]:.2f} mm"
    )
    shared: dict = {}
    for n in range(1, 5):
        name = f"nut_tap_{n}"
        item, _ = _hole(
            features, name, ["thread", "dia", "thru", "clock_deg", "note"], [-1, 0, 0]
        )
        if item.get("at_assembly") is not True or item.get("thru") is not True:
            raise CadError(f"{name}: expected a through tap transferred at assembly")
        for field in ("thread", "note", "dia", "clock_deg"):
            if shared.setdefault(field, item.get(field)) != item.get(field):
                raise CadError(f"{name}.{field}: nut taps disagree")
        _nominal(item, "clock_deg", name)
    values["nut_tap_count"] = 4
    values["nut_thread"] = _string(shared["thread"], "nut_tap_1.thread")
    _feed_process(values, parameters)


def _feed_process(values: dict, parameters: dict) -> None:
    """Bind the feed plan's millimetre and lug-relative values from its inch
    parameters, refusing bad relations here so both profiles do.

    Notch hold: the worst-case overhang, clear of the step, and the spacer
    offcut sawn from the bar, fitting beside the block within the jaws.
    Leadscrew clearance (before the notch): the pilot runs blind from OUTER
    END to ``lug_bore_depth_in``, past the lug face at every drawing size; the
    3/8 end mill plunges ``lug_bore_mill_in`` from OUTER END and, after the
    notch, the same from the lug face, Z zeroed on the face each enters, so
    each cuts exactly ``lug_bore_mill_in`` (tool_sizing checks it against the
    flutes) and the two meet through the thickest lug the drawing allows.
    Notch passes: the middle of the height, and each side with the cutter
    ``notch_side_overrun_in`` past its face.
    """
    length_in = values["length_nominal_in"]
    if "notch_overhang_max_in" in parameters:
        over = _positive(
            parameters["notch_overhang_max_in"], "process.notch_overhang_max_in"
        )
        values["notch_overhang_mm"] = over * 25.4
        over_min = _positive(
            parameters.get("notch_overhang_min_in"), "process.notch_overhang_min_in"
        )
        # LUG END hangs past the jaw side far enough for the cutter to reach
        # the step at the longest lug, and the head stays gripped.
        if not (
            values["lug_length_max_in"] < over_min <= over < values["overall_y_min_in"]
        ):
            raise CadError("process.notch_overhang_*_in: overhang must clear the step")
        if "vise_jaw_width_mm" in parameters and "blank_width_in" in parameters:
            jaw = _positive(
                parameters["vise_jaw_width_mm"], "process.vise_jaw_width_mm"
            )
            spacer = _positive(parameters["blank_width_in"], "process.blank_width_in")
            gripped = values["overall_y_max_in"] - over_min
            if not spacer + gripped < jaw / 25.4:
                raise CadError(
                    "process.blank_width_in: the spacer does not fit beside the block"
                )
    if "offcut_length_in" in parameters:
        offcut = _positive(parameters["offcut_length_in"], "process.offcut_length_in")
        values["offcut_length_mm"] = offcut * 25.4
    if "spacer_over_max_in" in parameters:
        _positive(parameters["spacer_over_max_in"], "process.spacer_over_max_in")
    if "lug_bore_depth_in" in parameters:
        depth = _positive(parameters["lug_bore_depth_in"], "process.lug_bore_depth_in")
        if not values["length_max_in"] - values["lug_x_min_in"] < depth:
            raise CadError("process.lug_bore_depth_in: must pass the lug face")
        if not depth < values["length_min_in"]:
            raise CadError("process.lug_bore_depth_in: must stop inside the block")
        values["lug_bore_floor_in"] = length_in - depth
        values["lug_bore_floor_mm"] = (length_in - depth) * 25.4
    if "lug_bore_mill_in" in parameters:
        mill = _positive(parameters["lug_bore_mill_in"], "process.lug_bore_mill_in")
        # Each plunge zeroes Z on the face it enters (OUTER END; the lug face
        # the notch just cut), so the thickest lug sets whether they meet and
        # the thinnest whether each stops inside it.
        if not values["length_max_in"] - values["lug_x_min_in"] < 2 * mill:
            raise CadError("process.lug_bore_mill_in: the two plunges must meet")
        if not mill < values["length_min_in"] - values["lug_x_max_in"]:
            raise CadError("process.lug_bore_mill_in: must stop inside the lug")
        if mill >= parameters.get("lug_bore_depth_in", math.inf):
            raise CadError("process.lug_bore_mill_in: must stop short of the pilot")
        # The lug-face plunge's floor over the parallels at the thinnest lug.
        floor = values["length_min_in"] - values["lug_x_max_in"] - mill
        values["lug_bore_back_floor_mm"] = floor * 25.4
        # Each plunge's depth below its own face, for tool_sizing.
        values["lug_bore_mill_mm"] = mill * 25.4
    if "notch_side_overrun_in" in parameters and "half_cutter_dia_mm" in parameters:
        overrun = _positive(
            parameters["notch_side_overrun_in"], "process.notch_side_overrun_in"
        )
        radius = (
            _positive(parameters["half_cutter_dia_mm"], "process.half_cutter_dia_mm")
            / 25.4
            / 2
        )
        height_in = values["height_nominal_in"]
        values["notch_pass_near_in"] = radius - overrun
        values["notch_pass_mid_in"] = height_in / 2
        values["notch_pass_far_in"] = height_in - radius + overrun
