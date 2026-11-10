"""Bindings for the released harmonic oblique-trammel feed lever (MHA-CH-06-TL-26)."""

import tomllib
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _inch_limits,
    _mid,
    _model_frame,
    _number,
    _positive,
    _string,
)


def load_feed_lever(path: Path, parameters: dict) -> CadData:
    """Bind the lever envelope and its two clearance holes near the zero end."""
    with path.open("rb") as source:
        raw = tomllib.load(source)
    if (
        raw.get("units") != "mm"
        or raw.get("part") != "ch-rocker-arm-tl-oblique-feed-lever"
    ):
        raise CadError(
            "cad: harmonic_feed_lever requires ch-rocker-arm-tl-oblique-feed-lever in mm"
        )
    _model_frame(raw)
    drawing = raw.get("drawing", {})
    if not isinstance(drawing, dict):
        raise CadError("cad.drawing: expected a table")
    values = {
        "part": raw["part"],
        "drawing_number": _string(drawing.get("number"), "cad.drawing.number"),
        "revision": _string(drawing.get("revision"), "cad.drawing.revision"),
    }
    features = raw.get("features")
    if not isinstance(features, dict):
        raise CadError("cad.features: expected a table")

    # Model X runs along the lever from the zero end, Y through the 1/2 in
    # thickness from the carrier seat (Y0) and Z across the 1 in width, the
    # zero edge at Z0.
    seat = features.get("carrier_seat")
    plane = seat.get("plane") if isinstance(seat, dict) else None
    if (
        not isinstance(plane, dict)
        or seat.get("frame") != "model"
        or seat.get("normal") != [0, -1, 0]
        or plane.get("axis") != "y"
        or _number(plane.get("value"), "carrier_seat.plane.value") != 0
    ):
        raise CadError("carrier_seat: expected the Y0 seat facing -Y")
    envelope = []
    for key in ("length", "thickness", "width"):
        band = _band(seat, key, "carrier_seat")
        _inch_limits(values, key, band)
        nominal = _positive(seat.get(f"{key}_nominal"), f"carrier_seat.{key}_nominal")
        if not band[0] <= nominal <= band[1]:
            raise CadError(f"carrier_seat.{key}_nominal: outside {key} band")
        values[f"{key}_mm"] = nominal
        envelope.append(StockAxis(key, f"blank_{key}_in", nominal))

    holes = sorted(
        (
            (name, item)
            for name, item in features.items()
            if name.startswith("bolt_hole_") and isinstance(item, dict)
        ),
        key=lambda pair: _number(pair[1].get("station_nominal"), pair[0]),
    )
    if len(holes) < 2:
        raise CadError("cad.features: expected the lever's bolt_hole_ holes")
    stations, tolerances, rows, diameters = [], [], [], []
    for index, (name, item) in enumerate(holes, 1):
        at = item.get("at")
        if (
            item.get("kind") != "hole"
            or item.get("frame") != "model"
            or item.get("axis") != [0, -1, 0]
            or item.get("thru") is not True
            or not isinstance(at, list)
            or len(at) != 3
            or _number(at[1], f"{name}.at") != values["thickness_mm"]
        ):
            raise CadError(f"{name}: expected a through hole down from the top face")
        station = _band(item, "station", name)
        row = _band(item, "width", name)
        if not station[0] <= _number(at[0], f"{name}.at") <= station[1]:
            raise CadError(f"{name}.at: station outside station band")
        if not row[0] <= -_number(at[2], f"{name}.at") <= row[1]:
            raise CadError(f"{name}.at: row outside width band")
        stations.append(_mid(station))
        tolerances.append((station[1] - station[0]) / 2)
        values[f"hole_{index}_x_mm"] = _mid(station)
        values[f"hole_{index}_station_band_mm"] = list(station)
        rows.append(row)
        diameters.append(_band(item, "dia", name))
    for key, bands in (("row", rows), ("hole_dia", diameters)):
        if any(band != bands[0] for band in bands):
            raise CadError(f"cad.{key}: holes disagree")
        _inch_limits(values, key, bands[0])
    values["hole_count"] = len(holes)
    values["hole_stations_in"] = ", ".join(f"{x / 25.4:.2f}" for x in stations)
    values["station_tol_in"] = min(tolerances) / 25.4
    values["hole_rows"] = [
        [f"H{index}", f"{x / 25.4:.3f}", f"{values['row_in']:.3f}"]
        for index, x in enumerate(stations, 1)
    ]

    general = raw.get("general_tolerances", {})
    if not isinstance(general, dict):
        raise CadError("cad.general_tolerances: expected a table")
    for key, field in (
        ("edge_break_in", "edge_break_r"),
        ("chamfer_max_in", "chamfer_max"),
        # The grip-end corner radius has no feature record; its one-place
        # title-block band is the only drawing limit available for it.
        ("linear_1pl_in", "linear_1pl"),
    ):
        values[key] = (
            _positive(general.get(field), f"general_tolerances.{field}") / 25.4
        )
    # Analysis fields are millimetres; the plan declares its blank in inches.
    for key in ("length", "thickness", "width"):
        if f"blank_{key}_in" in parameters:
            values[f"blank_{key}_mm"] = parameters[f"blank_{key}_in"] * 25.4
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())
