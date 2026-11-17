"""Bindings for the released end bracket of a jig."""

import math
import re
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
    _mid,
    _model_frame,
    _number,
    _positive,
    _read_manifest,
    _string,
)

# The single deliberate exception to "no values from prose" (AGENTS.md): the
# v48/v49 exports state the opposed thread zones only as words, in the tap callout
# note (mm, by face) and in the process note (inch, with the bottoming-tap tip
# marks). Both must match these exact phrasings and agree; anything else is
# refused. Replace with structured thread_zone/tip_mark fields once
# the CAD export provides them.
_NOTE_ZONES = re.compile(
    r"FULL THREAD (\d+\.\d+) TO (\d+\.\d+) mm FROM THE TOP FACE "
    r"AND (\d+\.\d+) TO (\d+\.\d+) mm FROM THE BOTTOM FACE"
)
_PROCESS_ZONES = re.compile(
    r"full thread (\.\d+)-(\.\d+) in from bar face and (\.\d+)-(\.\d+) in from KP08 "
    r"face; bottoming TIP insertion marks (\.\d+)-(\.\d+) in from bar face and "
    r"(\.\d+)-(\.\d+) in from KP08 face"
)
_PRINTED_IN = 0.0005  # The process note prints three-place inches.


def load_end_bracket(path: Path, parameters: dict, part: str) -> CadData:
    """Bind the bracket envelope, both shared-axis taps and their thread zones."""
    raw, values, features = _read_manifest(path, part, "end_bracket")
    _model_frame(raw)

    def feature(name: str) -> dict:
        item = features.get(name)
        if not isinstance(item, dict) or item.get("frame") != "model":
            raise CadError(f"cad.features.{name}: missing model-frame feature")
        return item

    def plane(item: dict, axis: str, where: str) -> float:
        value = item.get("plane")
        if not isinstance(value, dict) or value.get("axis") != axis:
            raise CadError(f"{where}.plane: expected a model {axis} plane")
        return _number(value.get("value"), f"{where}.plane.value")

    # Model X runs along the 2.71 length from the inner end, Y across the 1/2 in
    # bar thickness and Z up the 1 in bar width, the bar seat at Z0. The manifest
    # names the Y extent "width" and the Z extent "thickness"; here they keep the
    # flat bar's own names, as the declared blank does.
    seat = feature("bar_seat")
    if seat.get("normal") != [0, 0, -1] or plane(seat, "z", "bar_seat") != 0:
        raise CadError("bar_seat: expected the Z0 bar seat facing -Z")
    envelope = []
    for key, field, parameter in (
        ("length", "length", "blank_length_in"),
        ("thickness", "width", "blank_thickness_in"),
        ("width", "thickness", "blank_width_in"),
    ):
        band = _band(seat, field, "bar_seat")
        _inch_limits(values, key, band)
        nominal = _positive(seat.get(f"{field}_nominal"), f"bar_seat.{field}_nominal")
        if not band[0] <= nominal <= band[1]:
            raise CadError(f"bar_seat.{field}_nominal: outside {field} band")
        values[f"{key}_mm"] = nominal
        envelope.append(StockAxis(key, parameter, nominal))
    low_side = plane(feature("bracket_low_side"), "y", "bracket_low_side")

    holes = sorted(
        (
            (name, item)
            for name, item in features.items()
            if name.startswith("tap_") and isinstance(item, dict)
        ),
        key=lambda pair: _number(pair[1].get("station_nominal"), pair[0]),
    )
    if len(holes) != 2:
        raise CadError("cad.features: expected exactly two tap_ holes (H1, H2)")
    shared = {}
    stations, station_tolerances, rows = [], [], []
    for name, item in holes:
        at = item.get("at")
        if (
            item.get("kind") != "hole"
            or item.get("frame") != "model"
            or item.get("axis") != [0, 0, -1]
            or item.get("thru") is not True
            or item.get("height_from") != "bracket_low_side"
            or not isinstance(at, list)
            or len(at) != 3
            or _number(at[2], f"{name}.at") != values["width_mm"]
        ):
            raise CadError(f"{name}: expected a through hole down from the top face")
        for field in ("thread", "dia", "note"):
            if field not in item.get("requirements", []):
                raise CadError(f"{name}.{field}: missing drawing requirement")
            if shared.setdefault(field, item.get(field)) != item.get(field):
                raise CadError(f"{name}.{field}: holes disagree")
        station = _band(item, "station", name)
        row = _band(item, "height", name)
        if not station[0] <= _number(at[0], f"{name}.at") <= station[1]:
            raise CadError(f"{name}.at: station outside station band")
        if not row[0] <= _number(at[1], f"{name}.at") - low_side <= row[1]:
            raise CadError(f"{name}.at: row outside height band")
        stations.append(_mid(station))
        station_tolerances.append((station[1] - station[0]) / 2)
        values[f"hole_{len(stations)}_station_band_mm"] = list(station)
        rows.append(row)
    if any(row != rows[0] for row in rows):
        raise CadError("cad.row: holes disagree on the row band")
    _inch_limits(values, "row", rows[0])
    values["row_mm"] = _mid(rows[0])
    values["thread"] = _string(shared["thread"], "tap_1.thread")
    _inch_limits(values, "tap_drill", _band(holes[0][1], "dia", holes[0][0]))
    values["hole_count"] = len(holes)
    values["hole_stations_mm"] = ", ".join(f"{x:.3f}" for x in stations)
    values["hole_x_in"] = [x / 25.4 for x in stations]
    values["station_tol_mm"] = min(station_tolerances)
    values["station_tol_in"] = values["station_tol_mm"] / 25.4
    values["hole_rows"] = [
        [f"H{index}", f"{x / 25.4:.4f} ({x:.3f} mm)", f"{values['row_in']:.4f}"]
        for index, x in enumerate(stations, 1)
    ]

    note = _string(shared["note"], "tap_1.note")
    zones = _NOTE_ZONES.search(note)
    if zones is None:
        raise CadError("tap_1.note: expected the drawing's full-thread zones")
    top_low, top_high, bottom_low, bottom_high = (float(v) for v in zones.groups())
    # The bar seat is the bottom face (Z0); the KP08 seats on the top face.
    for key, band in (
        ("bar_thread", (bottom_low, bottom_high)),
        ("kp08_thread", (top_low, top_high)),
    ):
        if band[0] > band[1]:
            raise CadError(f"tap_1.note: reversed {key} zone")
        _inch_limits(values, key, band)
    notes = raw.get("notes")
    process = notes.get("process") if isinstance(notes, dict) else None
    marks = _PROCESS_ZONES.search(_string(process, "cad.notes.process"))
    if marks is None:
        raise CadError("cad.notes.process: expected the thread zones and tip marks")
    inches = [float(v) for v in marks.groups()]
    for key, (low, high) in (
        ("bar_thread", inches[0:2]),
        ("kp08_thread", inches[2:4]),
    ):
        stated = (values[f"{key}_min_in"], values[f"{key}_max_in"])
        if not all(
            math.isclose(a, b, abs_tol=_PRINTED_IN) for a, b in zip(stated, (low, high))
        ):
            raise CadError(f"cad.notes.process: {key} disagrees with the tap note")
    for key, (low, high) in (("bar_tip", inches[4:6]), ("kp08_tip", inches[6:8])):
        if low > high:
            raise CadError(f"cad.notes.process: reversed {key} mark")
        values[f"{key}_min_in"] = low
        values[f"{key}_max_in"] = high
    # One authored flag per face, measured from the tap's physical tip as the
    # process note states the marks. Each flag, ± the authored placement
    # tolerance, must sit in its face's tip window, and the two deepest tips
    # together must stay under the thinnest bracket, or the taps could meet.
    tolerance = _number(parameters.get("tap_flag_tol_in"), "process.tap_flag_tol_in")
    if tolerance < 0:
        raise CadError("process.tap_flag_tol_in: expected a nonnegative tolerance")
    reach = 0.0
    for key in ("bar", "kp08"):
        at = f"process.{key}_tap_flag_in"
        flag = _positive(parameters.get(f"{key}_tap_flag_in"), at)
        low, high = values[f"{key}_tip_min_in"], values[f"{key}_tip_max_in"]
        if flag - tolerance < low or flag + tolerance > high:
            raise CadError(
                f"{at}: {flag:g} ±{tolerance:g} leaves the drawing's tip window "
                f"{low:.3f}–{high:.3f}"
            )
        reach += flag + tolerance
    if reach >= values["width_min_in"]:
        raise CadError(
            f"process: the deepest tap tips reach {reach:.3f} from both faces, not "
            f"under the {values['width_min_in']:.3f} minimum width; the taps could meet"
        )
    # Setup 3's beam: the hole row spans the gap between two parallels against
    # the jaws, pinned at their centres across the part's thickness.
    parallel = _positive(
        parameters.get("parallel_thickness_mm"), "process.parallel_thickness_mm"
    )
    values["parallel_near_mm"] = parallel / 2
    values["parallel_far_mm"] = values["thickness_mm"] - parallel / 2

    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())
