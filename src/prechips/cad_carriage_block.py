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
# Stations and rows print at three places, so the model point may sit up to
# half a last digit (.0005 in) off the printed nominal.
_PRINTED_MM = 0.0127 + _TOL_MM


def load_pivot_block(path: Path, parameters: dict) -> CadData:
    """Bind the pivot block (MHA-CH-06-TL-22)."""
    return _load(path, parameters, "ch-rocker-arm-tl-oblique-pivot-block")


def load_feed_block(path: Path, parameters: dict) -> CadData:
    """Bind the feed block (MHA-CH-06-TL-32)."""
    return _load(path, parameters, "ch-rocker-arm-tl-oblique-feed-block")


def _close(a: float, b: float, tol: float = _TOL_MM) -> bool:
    return math.isclose(a, b, abs_tol=tol)


def _load(path: Path, parameters: dict, part: str) -> CadData:
    adapter, y_field, row_from = _PARTS[part]
    feed = adapter == "harmonic_feed_block"
    raw, values, features = _harmonic_manifest(path, part, adapter)
    _model_frame(raw)
    expected = _COMMON | (_FEED if feed else set())
    if set(features) != expected:
        raise CadError(f"cad.features: expected exactly {', '.join(sorted(expected))}")

    def feature(name: str, kind: str, requirements: list[str]) -> dict:
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

    def nominal(item: dict, field: str, where: str) -> float:
        band = _band(item, field, where)
        value = _number(item.get(f"{field}_nominal"), f"{where}.{field}_nominal")
        if not band[0] - _TOL_MM <= value <= band[1] + _TOL_MM:
            raise CadError(f"{where}.{field}_nominal: outside the {field} band")
        return value

    def bind(item: dict, field: str, where: str, key: str) -> float:
        _inch_limits(values, key, _band(item, field, where))
        value = nominal(item, field, where)
        values[f"{key}_mm"] = value
        values[f"{key}_nominal_in"] = value / 25.4
        return value

    # Model X runs along the 1.64 length (stations from the -X end), Y across
    # (rows from the -Y side on TL-22, the +Y side on TL-32), Z up from the
    # carriage seat (Z0, facing -Z) to the top face.
    seat = feature("carriage_seat", "face", _SEAT[adapter])
    plane = seat.get("plane")
    if seat.get("normal") != [0, 0, -1] or plane != {
        "frame": "model",
        "axis": "z",
        "value": 0,
    }:
        raise CadError("carriage_seat: expected the Z0 carriage seat facing -Z")
    length = bind(seat, "length", "carriage_seat", "length")
    y_length = bind(seat, y_field, "carriage_seat", y_field)
    height = bind(seat, "height", "carriage_seat", "height")
    _inch_limits(values, "y_length", _band(seat, y_field, "carriage_seat"))
    values["y_length_mm"] = y_length
    x_end = -length / 2
    envelope = (
        StockAxis("length", "blank_length_in", y_length),
        StockAxis("width", "blank_width_in", length),
        StockAxis("thickness", "blank_thickness_in", height),
    )

    def hole(name: str, requirements: list[str], axis: list) -> tuple[dict, list]:
        item = feature(name, "hole", requirements)
        at = item.get("at")
        if (
            item.get("axis") != axis
            or not isinstance(at, list)
            or len(at) != 3
            or item.get("thru", True) is not True
        ):
            raise CadError(f"{name}: expected a hole along {axis}")
        return item, [_number(v, f"{name}.at") for v in at]

    def plan_position(item: dict, at: list, name: str) -> tuple[float, float]:
        """Return the hole's model Y origin edge after checking both offsets."""
        if (
            item.get("station_from") != "minus_x_end"
            or item.get("row_from") != row_from
        ):
            raise CadError(f"{name}: expected stations from -X, rows from {row_from}")
        station = nominal(item, "station", name)
        row = nominal(item, "row", name)
        if not _close(at[0] - x_end, station, _PRINTED_MM) or not _close(at[2], height):
            raise CadError(f"{name}.at: station disagrees with the -X end")
        return station, at[1] - row if row_from == "minus_y_side" else at[1] + row

    # Pivot seat: flat-floored .375 down from the top, tap through below it.
    bore, bore_at = hole("pivot_bore", ["dia", "depth", "station", "row"], [0, 0, -1])
    if bore.get("floor") != "flat" or "thru" in bore:
        raise CadError("pivot_bore: expected a flat-floored blind bore")
    bore_station, y_edge = plan_position(bore, bore_at, "pivot_bore")
    bind(bore, "dia", "pivot_bore", "bore_dia")
    bind(bore, "depth", "pivot_bore", "bore_depth")
    bind(bore, "station", "pivot_bore", "bore_x")
    bind(bore, "row", "pivot_bore", "bore_y")
    tap, tap_at = hole("pivot_tap", ["thread", "dia", "thru"], [0, 0, -1])
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
    for n in range(1, 5):
        name = f"carriage_hole_{n}"
        item, at = hole(name, ["dia", "thru", "station", "row"], [0, 0, -1])
        if item.get("thru") is not True:
            raise CadError(f"{name}: expected a through hole")
        station, edge = plan_position(item, at, name)
        if not _close(edge, y_edge, 2 * _PRINTED_MM):
            raise CadError(f"{name}.at: row origin disagrees with the pivot bore")
        cbore = feature(f"carriage_counterbore_{n}", "counterbore", ["dia", "floor"])
        if cbore.get("parent") != name or cbore.get("floor_from") != "carriage_seat":
            raise CadError(f"carriage_counterbore_{n}: expected {name}'s counterbore")
        for key, source, field in (
            ("hole_dia", item, "dia"),
            ("cbore_dia", cbore, "dia"),
            ("cbore_floor", cbore, "floor"),
            ("station", item, "station"),
            ("row", item, "row"),
        ):
            band = (_band(source, field, name), nominal(source, field, name))
            if key in ("station", "row"):
                shared.setdefault(key, set()).add(band)
            elif shared.setdefault(key, band) != band:
                raise CadError(f"{name}.{field}: carriage holes disagree")
        depth_ref = _positive(cbore.get("depth_ref"), f"carriage_counterbore_{n}")
        if not _close(depth_ref, height - shared["cbore_floor"][1]):
            raise CadError(f"carriage_counterbore_{n}.depth_ref: not height − floor")
        points.append((station, nominal(item, "row", name)))
    for key in ("hole_dia", "cbore_dia", "cbore_floor"):
        band, value = shared[key]
        _inch_limits(values, key, band)
        values[f"{key}_mm"] = value
        values[f"{key}_nominal_in"] = value / 25.4
    values["cbore_depth_in"] = depth_ref / 25.4
    for key in ("station", "row"):
        if len(shared[key]) != 2:
            raise CadError(f"carriage holes: expected two {key} bands")
        for index, (band, value) in enumerate(sorted(shared[key], key=lambda b: b[1])):
            label = f"hole_{'x' if key == 'station' else 'y'}{index + 1}"
            _inch_limits(values, label, band)
            values[f"{label}_mm"] = value
            values[f"{label}_nominal_in"] = value / 25.4
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
    # Station and row tolerances print one band for every hole.
    values["hole_x_tol_in"] = (values["hole_x1_max_in"] - values["hole_x1_min_in"]) / 2
    values["hole_y_tol_in"] = (values["hole_y1_max_in"] - values["hole_y1_min_in"]) / 2

    if feed:
        _feed(features, values, seat, length, height, y_edge, hole, nominal, bind)
    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    # A centred vise hold leaves equal insets (negative overhangs) at both jaw
    # sides: (span along the jaws − jaw width) / 2, for each span a hold uses.
    if "vise_jaw_width_mm" in parameters:
        jaw = _positive(parameters["vise_jaw_width_mm"], "process.vise_jaw_width_mm")
        for key, along in (
            ("blank", values.get("blank_length_mm")),
            ("x", length),
            ("y", y_length),
        ):
            if along is not None:
                values[f"centred_overhang_{key}_mm"] = (along - jaw) / 2
    return CadData(values, StockRequirement("in", envelope), path.resolve())


def _feed(features, values, seat, length, height, y_edge, hole, nominal, bind) -> None:
    """Bind the feed block's lug, leadscrew clearance and assembly-transferred taps."""
    bind(seat, "lug_x", "carriage_seat", "lug_x")
    bind(seat, "lug_length", "carriage_seat", "lug_length")
    lug_end = y_edge - values["overall_y_mm"]
    # A plain through hole under the title block (no process word on the sheet).
    bore, at = hole("leadscrew_bore", ["dia", "thru", "row", "height"], [-1, 0, 0])
    if (
        bore.get("thru") is not True
        or "process" in bore
        or bore.get("row_from") != "lug_end"
        or bore.get("height_from") != "carriage_seat"
    ):
        raise CadError("leadscrew_bore: expected a plain through hole from the lug end")
    row = bind(bore, "row", "leadscrew_bore", "screw_y")
    z = bind(bore, "height", "leadscrew_bore", "screw_z")
    if (
        not _close(at[0], length / 2)
        or not _close(at[1] - lug_end, row)
        or not _close(at[2], z)
        or row >= values["lug_length_mm"]
        or not 0 < z < height
    ):
        raise CadError("leadscrew_bore.at: expected on the lug, from its +X face")
    bind(bore, "dia", "leadscrew_bore", "screw_dia")
    values["screw_z_band_text"] = (
        f"{values['screw_z_band_mm'][0]:.2f}–{values['screw_z_band_mm'][1]:.2f} mm"
    )
    shared: dict = {}
    for n in range(1, 5):
        name = f"nut_tap_{n}"
        item, _ = hole(name, ["thread", "dia", "thru", "clock_deg", "note"], [-1, 0, 0])
        if item.get("at_assembly") is not True or item.get("thru") is not True:
            raise CadError(f"{name}: expected a through tap transferred at assembly")
        for field in ("thread", "note", "dia", "clock_deg"):
            if shared.setdefault(field, item.get(field)) != item.get(field):
                raise CadError(f"{name}.{field}: nut taps disagree")
        nominal(item, "clock_deg", name)
    values["nut_tap_count"] = 4
    values["nut_thread"] = _string(shared["thread"], "nut_tap_1.thread")
    values["nut_tap_note"] = _string(shared["note"], "nut_tap_1.note")
    low, high = (_number(v, "nut_tap_1.clock_deg") for v in shared["clock_deg"])
    values["nut_clock_min_deg"] = low
    values["nut_clock_max_deg"] = high
