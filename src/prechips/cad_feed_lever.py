"""Bindings for the released harmonic oblique-trammel feed lever (MHA-CH-06-TL-26)."""

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
    _mid,
    _model_frame,
    _number,
    _positive,
)


def load_feed_lever(path: Path, parameters: dict) -> CadData:
    """Bind the lever envelope, its two clearance holes and its grip corners."""
    raw, values, features = _harmonic_manifest(
        path, "ch-rocker-arm-tl-oblique-feed-lever", "harmonic_feed_lever"
    )
    _model_frame(raw)

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
    if len(holes) != 2:
        raise CadError("cad.features: expected exactly two bolt_hole_ holes (H1, H2)")
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
        values[f"hole_{index}_station_band_mm"] = list(station)
        rows.append(row)
        diameters.append(_band(item, "dia", name))
    for key, bands in (("row", rows), ("hole_dia", diameters)):
        if any(band != bands[0] for band in bands):
            raise CadError(f"cad.{key}: holes disagree")
        _inch_limits(values, key, bands[0])
    values["hole_count"] = len(holes)
    values["hole_stations_in"] = ", ".join(f"{x / 25.4:.2f}" for x in stations)
    values["hole_x_in"] = [x / 25.4 for x in stations]
    values["station_tol_in"] = min(tolerances) / 25.4
    values["hole_rows"] = [
        [f"H{index}", f"{x / 25.4:.3f}", f"{values['row_in']:.3f}"]
        for index, x in enumerate(stations, 1)
    ]

    _edge_breaks(raw, values)
    # The two grip-end plan corners (drawing 2X R.2): one fillet record.
    corners = features.get("grip_corners")
    if (
        not isinstance(corners, dict)
        or corners.get("kind") != "fillet"
        or corners.get("frame") != "model"
        or corners.get("count") != 2
    ):
        raise CadError("grip_corners: expected the two grip-end corner fillets")
    radius = _band(corners, "radius", "grip_corners")
    nominal = _positive(corners.get("radius_nominal"), "grip_corners.radius_nominal")
    if not radius[0] <= nominal <= radius[1]:
        raise CadError("grip_corners.radius_nominal: outside radius band")
    _inch_limits(values, "corner_radius", radius)
    values["corner_radius_in"] = nominal / 25.4
    _blank_mm(values, parameters)
    # The hand sheet gives the vise overhang in inches; vise_hold reads mm.
    if "overhang_in" in parameters:
        values["overhang_mm"] = (
            _positive(parameters["overhang_in"], "process.overhang_in") * 25.4
        )
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())
