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
    _shorthand,
    _trim,
)

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
    return _shorthand(value_mm / 25.4, places)


def _face_layout(blank: float, layout: dict) -> tuple:
    """Stage A spans, Stage B cuts and both strap sets on one blank, inches.

    Refuses a layout that leaves no Stage A span or puts a Stage B strap off
    Stage A's faced metal or in a Stage B cut.
    """
    toe, clear, overlap = layout["toe"], layout["clear"], layout["overlap"]
    mid, strap = layout["mid"], layout["strap"]
    outer, inner = layout["outer"], layout["inner"]
    if not outer < inner < blank - inner:
        raise CadError(
            "process.strap_b_*_in: expected outer < inner < blank length - inner"
        )
    a0, a1 = toe + clear, blank - toe - clear
    m0, m1 = mid - strap / 2 - clear, mid + strap / 2 + clear
    if not a0 < m0 < m1 < a1:
        raise CadError("process.strap_a_mid_x_in: the middle strap leaves no span")
    stage_a = ((a0, m0), (m1, a1))
    stage_b = ((0.0, a0 + overlap), (m0 - overlap, m1 + overlap), (a1 - overlap, blank))
    straps_b = (outer, inner, blank - inner, blank - outer)
    for x in straps_b:
        low, high = x - strap / 2 - clear, x + strap / 2 + clear
        on_a = any(start <= low and high <= end for start, end in stage_a)
        if not on_a or any(start < high and low < end for start, end in stage_b):
            raise CadError(
                "process.strap_b_*_in: a Stage B strap is off faced metal or in a cut"
            )
    # Stage A's end straps bear half their toe in from each end.
    straps_a = (toe / 2, mid, blank - toe / 2)
    return stage_a, stage_b, straps_a, straps_b


def _cut_supports(cut: tuple, straps: tuple) -> tuple:
    """The Stage B straps a cut bends on: the nearest on each side, or, for an
    end cut with none beyond it, the two nearest (the cut overhangs them)."""
    left = [x for x in straps if x < cut[0]]
    right = [x for x in straps if x > cut[1]]
    if left and right:
        return left[-1], right[0]
    return tuple(left[-2:]) if left else tuple(right[:2])


def _face_stations(parameters: dict, values: dict) -> None:
    """Bind Setup 2's strap layout and faced spans, inches from the blank's left end.

    Stage A faces two spans between the end straps and the middle strap, the
    cutter edge ``strap_clear_in`` off each strap; Stage B faces both ends and
    the strip under the middle strap, each ``face_overlap_in`` over Stage A,
    from four straps on Stage A's faced metal. The printed layout is the
    nominal blank's; every sawn length must take it. The milling_deflection
    supports and traverses are the same layout on the longest blank (its
    right-hand spans are the longest), in mm, so the beams cannot drift from
    the printed layout.
    """

    def get(key: str) -> float:
        return _positive(parameters.get(key), f"process.{key}")

    layout = {
        name: get(key)
        for name, key in (
            ("toe", "strap_toe_in"),
            ("clear", "strap_clear_in"),
            ("overlap", "face_overlap_in"),
            ("mid", "strap_a_mid_x_in"),
            ("strap", "strap_width_in"),
            ("outer", "strap_b_outer_in"),
            ("inner", "strap_b_inner_in"),
        )
    }
    _face_layout(get("blank_min_length_in"), layout)
    stage_a, stage_b, straps_a, straps_b = _face_layout(get("blank_length_in"), layout)
    values["face_stage_a_in"] = [list(span) for span in stage_a]
    values["face_stage_b_in"] = [list(span) for span in stage_b]
    values["face_straps_a_in"] = list(straps_a)
    values["face_straps_b_in"] = list(straps_b)
    stage_a, stage_b, straps_a, straps_b = _face_layout(
        get("blank_max_length_in"), layout
    )
    for key, span, supports in (
        ("a_left", stage_a[0], straps_a[:2]),
        ("a_right", stage_a[1], straps_a[1:]),
        *(
            (f"b_{side}", cut, _cut_supports(cut, straps_b))
            for side, cut in zip(("left", "mid", "right"), stage_b)
        ),
    ):
        values[f"face_{key}_mm"] = [span[0] * 25.4, span[1] * 25.4]
        values[f"face_{key}_supports_mm"] = [supports[0] * 25.4, supports[1] * 25.4]


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
    # Setup 1 sends any bar within the thickness band past Setup 2, so beams
    # through the finished thickness take its thinnest (the most flexible);
    # Setup 2 gets only bars over the band, so its unfaced metal is at least
    # the band's top.
    values["thickness_min_mm"] = values["thickness_band_mm"][0]
    values["thickness_max_mm"] = values["thickness_band_mm"][1]

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
            _shorthand(values[f"{tag.lower()}_x_in"], 2),
            _shorthand(values["stop_row_in"], 2),
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
    angles = {}
    for tag, name in _COUNTERSINKS:
        item = feature(name)
        if item.get("kind") != "countersink" or item.get("parent") != name.removesuffix(
            "_countersink"
        ):
            raise CadError(f"{name}: expected the countersink of {tag}")
        if "angle_deg" not in item.get("requirements", []):
            raise CadError(f"{name}.angle_deg: missing drawing requirement")
        angles[name] = (
            _positive(item.get("angle_deg"), f"{name}.angle_deg"),
            _positive(item.get("angle_tol_deg"), f"{name}.angle_tol_deg"),
        )
    if len(set(angles.values())) != 1:
        found = "; ".join(
            f"{name} {angle:g}° ±{tol:g}°" for name, (angle, tol) in angles.items()
        )
        raise CadError(f"cad.csk_angle_deg: countersinks disagree: {found}")
    values["csk_angle_deg"], values["csk_angle_tol_deg"] = next(iter(angles.values()))

    # Vise holds (plan copies of the shop vise jaw width and parallel
    # thickness). Setup 4 drills P1/P2 in the end overhang, clear of the jaw
    # side; Setup 5 drills each spotted hole between the jaws, clear of the
    # parallels under both long edges.
    jaw = _positive(parameters.get("vise_jaw_width_mm"), "process.vise_jaw_width_mm")
    parallel = _positive(
        parameters.get("parallel_thickness_mm"), "process.parallel_thickness_mm"
    )
    # Each arriving end sits overhang_in to overhang_max_in past its jaw side.
    # The plan does not split the blank allowance between the two ends (hold 1
    # only cleans up the left end; hold 2 cuts the right end to length), so
    # either end may lose all of it: each stop hole must clear the jaw side at
    # the shortest overhang with the longest blank's whole allowance off its end.
    over = _positive(parameters.get("overhang_in"), "process.overhang_in") * 25.4
    over_max = (
        _positive(parameters.get("overhang_max_in"), "process.overhang_max_in") * 25.4
    )
    if over_max < over:
        raise CadError("process.overhang_max_in: below overhang_in")
    values["overhang_mm"] = over
    values["overhang_max_mm"] = over_max
    blank = _positive(parameters.get("blank_length_in"), "process.blank_length_in")
    blank_min = _positive(
        parameters.get("blank_min_length_in"), "process.blank_min_length_in"
    )
    blank_max = _positive(
        parameters.get("blank_max_length_in"), "process.blank_max_length_in"
    )
    if not blank_min <= blank <= blank_max:
        raise CadError(
            "process.blank_length_in: outside blank_min_length_in..blank_max_length_in"
        )
    # The shortest blank must still reach the longest finished length.
    _trim(blank_min * 25.4, values["length_band_mm"][1], "blank_min_length_in")
    # Hold 2 may cut to the shortest finished length, so ZERO END's clean-up
    # can take up to the longest blank less that.
    allowance = 2 * _trim(
        blank_max * 25.4, values["length_band_mm"][0], "blank_max_length_in"
    )
    values["blank_centred_overhang_mm"] = (blank * 25.4 - jaw) / 2
    values["blank_centred_overhang_in"] = values["blank_centred_overhang_mm"] / 25.4
    values["centred_overhang_mm"] = (length - jaw) / 2
    for tag, (low, high) in zip(("P1", "P2"), stations):
        inner = high if tag == "P1" else length - low
        if inner + stop_dia[1] / 2 >= over - allowance:
            raise CadError(
                f"process.overhang_in: {tag} is not clear of the jaw side in Setup 4 "
                "with a blank_max_length_in blank"
            )
    # Y0 is touched on ZERO EDGE in hold 1's right overhang: the finder must
    # clear that jaw side, at most overhang_max_in + jaw width from ZERO END,
    # and stay on the part.
    touch = _positive(parameters.get("y_touch_x_in"), "process.y_touch_x_in") * 25.4
    finder = (
        _positive(parameters.get("edge_finder_dia_in"), "process.edge_finder_dia_in")
        * 25.4
    )
    if not over_max + jaw < touch - finder / 2 < touch + finder / 2 < length:
        raise CadError(
            "process.y_touch_x_in: the Y0 touch is not in hold 1's right overhang"
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
    # milling_deflection stations (mm). Setup 3 holds the longest blank
    # centred on edge (the longest overhang); Setup 4 frames X from ZERO END,
    # each hold's jaw side the longest allowed overhang from its end (the
    # longest cantilever); Setup 5 holes are drilled across the gap between
    # the two parallels.
    blank_max_mm = blank_max * 25.4
    values["blank_max_length_mm"] = blank_max_mm
    values["blank_max_centred_overhang_mm"] = (blank_max_mm - jaw) / 2
    values["edges_jaw_mm"] = [
        values["blank_max_centred_overhang_mm"],
        values["blank_max_centred_overhang_mm"] + jaw,
    ]
    values["ends_hold1_jaw_mm"] = [over_max, over_max + jaw]
    values["ends_hold2_jaw_mm"] = [length - over_max - jaw, length - over_max]
    for tag, (low, high) in zip(("P1", "P2"), stations):
        values[f"{tag.lower()}_x_mm"] = (low + high) / 2
    values["parallel_gap_mm"] = [parallel, width - parallel]
    by_tag = {tag: y for tag, _, y, _ in spotted}
    values["spot_y_mm"] = [by_tag[tag] for tag, _ in _SPOTTED]
    values["screw_y_mm"] = [by_tag[tag] for tag, _ in _SCREWS]
    values["clamp_y_mm"] = [by_tag[tag] for tag, _ in _CLAMPS]
    values["hub_y_mm"] = by_tag["HUB"]

    _edge_breaks(raw, values)
    _face_stations(parameters, values)
    _blank_mm(values, parameters)
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())
