"""Bindings for the released harmonic oblique-trammel riser (MHA-CH-06-TL-24)."""

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
)
from .jig_diagrams import _inch, _trim

# Drawing tags by manifest feature. The stop-pin holes P1/P2 are drilled at
# their printed .XX stations; the other seven are spotted from the carrier
# (TL-21) at assembly, so the drawing prints their X/Y LOC REF only.
_STOPS = (("P1", "stop_hole_1"), ("P2", "stop_hole_2"))
_SCREWS = tuple((f"R{index}", f"screw_hole_{index}") for index in range(1, 5))
_HUB = (("HUB", "hub_hole"),)
_CLAMPS = (("CL", "cl_hole"), ("CR", "cr_hole"))
_SPOTTED = (*_SCREWS, *_HUB, *_CLAMPS)
_COUNTERSINKS = tuple((tag, f"{name}_countersink") for tag, name in _SCREWS)
_FEATURES = {
    "top_face",
    "carrier_seat",
    *(name for _, name in (*_STOPS, *_SPOTTED, *_COUNTERSINKS)),
}
# Setup 5 vise holds along the jaws, in preference order: centred, then the
# part's left end at the left jaw side, then its right end at the right one.
_HOLDS = ("C", "L", "R")


def _in(value_mm: float, places: int = 3) -> str:
    """Shop shorthand inches without the leading zero, as the sheet prints."""
    return _inch(value_mm / 25.4, places)


def load_riser(path: Path, parameters: dict) -> CadData:
    """Bind the riser envelope, its two stop-pin holes and the seven REF holes."""
    raw, values, features = _harmonic_manifest(
        path, "ch-rocker-arm-tl-oblique-riser", "harmonic_riser"
    )
    _model_frame(raw)
    if set(features) != _FEATURES:
        extra = sorted(set(features) - _FEATURES)
        missing = sorted(_FEATURES - set(features))
        raise CadError(
            f"cad.features: expected the riser's {len(_FEATURES)} features; extra {extra}, "
            f"missing {missing}"
        )

    def feature(name: str) -> dict:
        item = features[name]
        if not isinstance(item, dict) or item.get("frame") != "model":
            raise CadError(f"cad.features.{name}: missing model-frame feature")
        return item

    def plane(item: dict, where: str) -> float:
        value = item.get("plane")
        if not isinstance(value, dict) or value.get("axis") != "z":
            raise CadError(f"{where}.plane: expected a model z plane")
        return _number(value.get("value"), f"{where}.plane.value")

    # Model X runs along the 13.80 length from the left end, Y across the 1.69
    # width from the lower (stop-pin) edge and Z through the .24 thickness, the
    # carrier seat at Z0: the drawing's lower-left corner is the origin.
    top = feature("top_face")
    seat = feature("carrier_seat")
    if top.get("normal") != [0, 0, 1] or seat.get("normal") != [0, 0, -1]:
        raise CadError("top_face/carrier_seat: expected +Z top and -Z seat faces")
    if plane(seat, "carrier_seat") != 0:
        raise CadError("carrier_seat: expected the Z0 seat")
    envelope = []
    for key, field in (
        ("length", "length"),
        ("width", "width"),
        ("thickness", "height"),
    ):
        band = _band(top, field, "top_face")
        _inch_limits(values, key, band)
        nominal = _positive(top.get(f"{field}_nominal"), f"top_face.{field}_nominal")
        if not band[0] <= nominal <= band[1]:
            raise CadError(f"top_face.{field}_nominal: outside {field} band")
        values[f"{key}_mm"] = nominal
        envelope.append(StockAxis(key, f"blank_{key}_in", nominal))
    if plane(top, "top_face") != values["thickness_mm"]:
        raise CadError("top_face.plane: expected the face at the nominal thickness")
    if _band(seat, "height", "carrier_seat") != tuple(values["thickness_band_mm"]):
        raise CadError("carrier_seat.height: disagrees with the top face")
    length, width = values["length_mm"], values["width_mm"]

    def hole(name: str) -> tuple[dict, float, float]:
        item = feature(name)
        at = item.get("at")
        if (
            item.get("kind") != "hole"
            or item.get("axis") != [0, 0, -1]
            or item.get("thru") is not True
            or not isinstance(at, list)
            or len(at) != 3
            or _number(at[2], f"{name}.at") != values["thickness_mm"]
        ):
            raise CadError(f"{name}: expected a through hole down from the top face")
        x, y = _number(at[0], f"{name}.at"), _number(at[1], f"{name}.at")
        if not (0 < x < length and 0 < y < width):
            raise CadError(f"{name}.at: off the riser")
        return item, x, y

    def shared(tags: tuple, key: str) -> tuple[float, float]:
        bands = {_band(feature(name), "dia", name) for _, name in tags}
        if len(bands) != 1:
            raise CadError(f"cad.{key}: holes disagree on the diameter band")
        band = bands.pop()
        _inch_limits(values, key, band)
        return band

    # P1/P2: toleranced .XX stations and row from the lower-left corner.
    row_bands, stations = [], []
    for tag, name in _STOPS:
        item, x, y = hole(name)
        station, row = _band(item, "station", name), _band(item, "height", name)
        if not (station[0] <= x <= station[1] and row[0] <= y <= row[1]):
            raise CadError(f"{name}.at: outside its station/row band")
        _inch_limits(values, f"{tag.lower()}_x", station)
        stations.append(station)
        row_bands.append(row)
    if row_bands[0] != row_bands[1]:
        raise CadError("cad.stop_row: P1 and P2 disagree on the row band")
    _inch_limits(values, "stop_row", row_bands[0])
    values["stop_station_tol_in"] = (
        min((high - low) / 2 for low, high in stations) / 25.4
    )
    stop_dia = shared(_STOPS, "stop_dia")
    values["stop_rows"] = [
        [
            tag,
            _inch(values[f"{tag.lower()}_x_in"], 2),
            _inch(values["stop_row_in"], 2),
        ]
        for tag, _ in _STOPS
    ]

    # The seven spotted holes carry no position requirement; a toleranced
    # station or row would make the REF locations drill targets.
    spotted = []
    for tag, name in _SPOTTED:
        item, x, y = hole(name)
        if {"station", "width", "height"} & set(item.get("requirements", [])):
            raise CadError(f"{name}: expected REF X/Y LOC (spotted from TL-21)")
        if (
            _number(item.get("station_nominal"), f"{name}.station_nominal") != x
            or _number(item.get("width_nominal"), f"{name}.width_nominal") != y
        ):
            raise CadError(f"{name}: REF X/Y disagree with its centre")
        spotted.append((tag, x, y, _band(item, "dia", name)))
    shared(_SCREWS, "screw_dia")
    shared(_HUB, "hub_dia")
    shared(_CLAMPS, "clamp_dia")
    shared(_COUNTERSINKS, "csk_dia")
    angles = set()
    for tag, name in _COUNTERSINKS:
        item = feature(name)
        if item.get("kind") != "countersink" or item.get("parent") != name.removesuffix(
            "_countersink"
        ):
            raise CadError(f"{name}: expected the countersink of {tag}")
        if "angle_deg" not in item.get("requirements", []):
            raise CadError(f"{name}.angle_deg: missing drawing requirement")
        angles.add(
            (
                _positive(item.get("angle_deg"), f"{name}.angle_deg"),
                _positive(item.get("angle_tol_deg"), f"{name}.angle_tol_deg"),
            )
        )
    if len(angles) != 1:
        raise CadError("cad.csk_angle_deg: countersinks disagree")
    values["csk_angle_deg"], values["csk_angle_tol_deg"] = angles.pop()

    # Vise holds (plan copies of the shop vise jaw width and parallel
    # thickness). Setup 4 drills P1/P2 in the end overhang, clear of the jaw
    # side; Setup 5 drills each spotted hole between the jaws, clear of the
    # parallels under both long edges.
    jaw = _positive(parameters.get("vise_jaw_width_mm"), "process.vise_jaw_width_mm")
    parallel = _positive(
        parameters.get("parallel_thickness_mm"), "process.parallel_thickness_mm"
    )
    # Each arriving end sits overhang_in past its jaw side. The plan does not
    # split the blank allowance between the two ends (hold 1 only cleans up
    # the left end; hold 2 cuts the right end to length), so either end may
    # lose all of it: each stop hole must clear the jaw side with the whole
    # allowance off its end.
    over = _positive(parameters.get("overhang_in"), "process.overhang_in") * 25.4
    values["overhang_mm"] = over
    blank = _positive(parameters.get("blank_length_in"), "process.blank_length_in")
    allowance = 2 * _trim(blank * 25.4, length, "blank_length_in")
    values["blank_centred_overhang_mm"] = (blank * 25.4 - jaw) / 2
    values["blank_centred_overhang_in"] = values["blank_centred_overhang_mm"] / 25.4
    values["centred_overhang_mm"] = (length - jaw) / 2
    for tag, (low, high) in zip(("P1", "P2"), stations):
        inner = high if tag == "P1" else length - low
        if inner + stop_dia[1] / 2 >= over - allowance:
            raise CadError(
                f"process.overhang_in: {tag} is not clear of the jaw side in Setup 4"
            )
    spans = {
        "C": ((length - jaw) / 2, (length + jaw) / 2),
        "L": (0.0, jaw),
        "R": (length - jaw, length),
    }
    spot_rows = []
    for tag, x, y, dia in sorted(spotted, key=lambda item: item[1]):
        radius = dia[1] / 2
        if not parallel + radius < y < width - parallel - radius:
            raise CadError(f"{tag}: REF hole over a parallel in Setup 5")
        hold = next(
            (
                key
                for key in _HOLDS
                if spans[key][0] < x - radius < x + radius < spans[key][1]
            ),
            None,
        )
        if hold is None:
            raise CadError(
                f"{tag}: REF hole is not between the jaws in any Setup 5 hold"
            )
        spot_rows.append(
            [tag, _in(x, 2), _in(y, 2), f"{_in(dia[0])}–{_in(dia[1])}", hold]
        )
    values["spot_rows"] = spot_rows
    values["spot_count"] = len(spot_rows)
    values["spot_points_in"] = [[tag, x / 25.4, y / 25.4] for tag, x, y, _ in spotted]
    values["stop_points_in"] = [
        [tag, values[f"{tag.lower()}_x_in"], values["stop_row_in"]] for tag, _ in _STOPS
    ]
    # milling_deflection stations (mm). Setup 3 holds the blank centred on
    # edge; Setup 4 frames X from ZERO END, each hold's jaw side the whole
    # overhang from its end (the longest overhang any end cleanup leaves);
    # Setup 5 holes are drilled across the gap between the two parallels.
    blank_mm = blank * 25.4
    values["edges_jaw_mm"] = [
        values["blank_centred_overhang_mm"],
        blank_mm - values["blank_centred_overhang_mm"],
    ]
    values["ends_hold1_jaw_mm"] = [over, over + jaw]
    values["ends_hold2_jaw_mm"] = [length - over - jaw, length - over]
    for tag, (low, high) in zip(("P1", "P2"), stations):
        values[f"{tag.lower()}_x_mm"] = (low + high) / 2
    values["parallel_gap_mm"] = [parallel, width - parallel]
    by_tag = {tag: y for tag, _, y, _ in spotted}
    values["spot_y_mm"] = [by_tag[tag] for tag, _ in _SPOTTED]
    values["screw_y_mm"] = [by_tag[tag] for tag, _ in _SCREWS]
    values["clamp_y_mm"] = [by_tag[tag] for tag, _ in _CLAMPS]
    values["hub_y_mm"] = by_tag["HUB"]

    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())
