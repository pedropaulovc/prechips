"""Bindings for the harmonic leadscrew kit rework (MHA-CH-06-TL-VN-84).

A purchased ReliaBot Tr8x2 screw and brass flange nut, one manifest with two
members: the LeadScrew (saved default) is cut to length and takes five
set-screw flats; the FeedNut's features carry ``configuration = "FeedNut"`` and
bind its own member STEP (its spigot is faced off and its holes countersunk).
Screw stations run along model +Y from the NEAR END; nut lengths from its
seat face.
"""

import math
from pathlib import Path

from .cad import (
    CadData,
    CadError,
    StockAxis,
    StockRequirement,
    _band,
    _harmonic_manifest,
    _model_frame,
    _number,
    _positive,
    _string,
)

_PART = "ch-rocker-arm-tl-vn-oblique-leadscrew-kit"
_NUT = "FeedNut"
_FLATS = ("near_kp08", "far_kp08", "handwheel")
_CLOCKED = ("near_kp08", "far_kp08")


def _limits(values: dict, key: str, band: tuple[float, float], nominal: float) -> None:
    """Bind ``<key>_mm`` (nominal), ``_min_mm``/``_max_mm`` and ``_band_mm``."""
    if not band[0] <= nominal <= band[1]:
        raise CadError(f"cad.{key}: nominal lies outside source limits")
    values[f"{key}_mm"] = nominal
    values[f"{key}_min_mm"], values[f"{key}_max_mm"] = band
    values[f"{key}_band_mm"] = list(band)


def load_leadscrew_kit(path: Path, parameters: dict) -> CadData:
    """Bind the screw's cut and flats and the nut's facing and countersinks."""
    raw, values, features = _harmonic_manifest(path, _PART, "harmonic_leadscrew_kit")
    _model_frame(raw)
    members = raw.get("member_steps")
    if not isinstance(members, dict) or set(members) != {_NUT}:
        raise CadError("cad.member_steps: expected exactly the FeedNut member STEP")

    def feature(name: str, kind: str, member: str | None = None) -> dict:
        item = features.get(name)
        if (
            not isinstance(item, dict)
            or item.get("kind") != kind
            or item.get("frame") != "model"
            or item.get("configuration") != member
        ):
            where = f" of member {member}" if member else ""
            raise CadError(f"cad.{name}: expected a model-frame {kind}{where}")
        return item

    def nominal(item: dict, field: str, key: str) -> float:
        value = _positive(item.get(f"{field}_nominal"), f"cad.{key}_nominal")
        _limits(values, key, _band(item, field, key), value)
        return value

    # --- Screw: axis +Y, NEAR END y = 0 facing -Y, cut end y = length. -------
    near, cut = feature("near_end", "face"), feature("cut_end", "face")
    if near.get("normal") != [0, -1, 0] or cut.get("normal") != [0, 1, 0]:
        raise CadError("cad: expected the screw's end faces along -Y and +Y")
    length = nominal(near, "length", "length")
    if _band(cut, "length", "cut_end") != _band(near, "length", "near_end"):
        raise CadError("cad: the two end faces disagree on the cut length")
    plane = cut.get("plane")
    if (
        not isinstance(plane, dict)
        or plane.get("axis") != "y"
        or not math.isclose(
            _number(plane.get("value"), "cad.cut_end.plane.value"), length
        )
    ):
        raise CadError("cad.cut_end: plane is not at the cut length")
    values["stock_length_mm"] = _positive(
        near.get("stock_length"), "cad.near_end.stock_length"
    )
    values["major_dia_mm"] = _positive(near.get("major_dia"), "cad.near_end.major_dia")
    values["thread"] = _string(near.get("thread"), "cad.near_end.thread")
    values["end_chamfer_mm"] = _positive(
        near.get("end_chamfer"), "cad.near_end.end_chamfer"
    )
    if values["stock_length_mm"] <= values["length_max_mm"]:
        raise CadError("cad: the supplied screw is not longer than the cut")

    cutter = _positive(
        parameters.get("flat_cutter_dia_mm"), "process.flat_cutter_dia_mm"
    )
    afs, depths, lengths = set(), set(), set()
    af_nominals, length_nominals, open_flats = set(), set(), []
    for name in _FLATS:
        item = feature(f"{name}_flat", "flat")
        if item.get("normal") != [1, 0, 0] or item.get("clock_deg") != 0:
            raise CadError(f"cad.{name}_flat: expected the clock-0 flat facing +X")
        start = nominal(item, "station", f"{name}_station")
        _positive(item.get("set_screw_station"), f"cad.{name}_flat.set_screw_station")
        # The cutter crosses the screw with its edge on the flat's start: its
        # centre stands half a cutter on, from the NEAR END.
        values[f"{name}_centre_mm"] = start + cutter / 2
        afs.add(_band(item, "af", f"{name}_flat"))
        af_nominals.add(
            _positive(item.get("af_nominal"), f"cad.{name}_flat.af_nominal")
        )
        depths.add(
            _positive(item.get("depth_nominal"), f"cad.{name}_flat.depth_nominal")
        )
        if item.get("runout") is True:
            if "length" in item.get("requirements", []):
                raise CadError(f"cad.{name}_flat: an open flat has no length")
            open_flats.append(name)
        else:
            lengths.add(_band(item, "length", f"{name}_flat"))
            length_nominals.add(
                _positive(item.get("length_nominal"), f"cad.{name}_flat.length_nominal")
            )
    if open_flats != ["handwheel"]:
        raise CadError(
            "cad: expected only the handwheel flat to run out through the cut end"
        )
    clocks = set()
    for name in _CLOCKED:
        item = feature(f"{name}_clock_flat", "flat")
        if item.get("station_nominal") != values[f"{name}_station_mm"]:
            raise CadError(f"cad.{name}_clock_flat: not at its clock-0 flat's station")
        clock = _positive(
            item.get("clock_deg_nominal"), f"cad.{name}_clock_flat.clock_deg_nominal"
        )
        normal = item.get("normal")
        expected = [math.cos(math.radians(clock)), 0.0, math.sin(math.radians(clock))]
        if (
            not isinstance(normal, list)
            or len(normal) != 3
            or any(
                not math.isclose(
                    _number(a, f"cad.{name}_clock_flat.normal"), b, abs_tol=1e-9
                )
                for a, b in zip(normal, expected)
            )
        ):
            raise CadError(
                f"cad.{name}_clock_flat: normal disagrees with its clock angle"
            )
        clocks.add((_band(item, "clock_deg", f"{name}_clock_flat"), clock))
        afs.add(_band(item, "af", f"{name}_clock_flat"))
        af_nominals.add(
            _positive(item.get("af_nominal"), f"cad.{name}_clock_flat.af_nominal")
        )
        depths.add(
            _positive(item.get("depth_nominal"), f"cad.{name}_clock_flat.depth_nominal")
        )
        lengths.add(_band(item, "length", f"{name}_clock_flat"))
        length_nominals.add(
            _positive(
                item.get("length_nominal"), f"cad.{name}_clock_flat.length_nominal"
            )
        )
    if (
        len(afs) != 1
        or len(af_nominals) != 1
        or len(depths) != 1
        or len(lengths) != 1
        or len(length_nominals) != 1
        or len(clocks) != 1
    ):
        raise CadError("cad: the flats disagree on across-flat, depth, length or clock")
    af = afs.pop()
    af_nominal = af_nominals.pop()
    if not math.isclose(
        af_nominal, values["major_dia_mm"] - depths.pop(), abs_tol=1e-6
    ):
        raise CadError("cad: the flats' across-flat is not the major less their depth")
    _limits(values, "af", af, af_nominal)
    values["flat_depth_mm"] = values["major_dia_mm"] - af_nominal
    # Flat floor above the screw axis: the dividing-head work height less this.
    values["major_radius_mm"] = values["major_dia_mm"] / 2
    values["flat_floor_mm"] = af_nominal - values["major_radius_mm"]
    _limits(values, "flat_length", lengths.pop(), length_nominals.pop())
    clock_band, clock = clocks.pop()
    if not clock_band[0] <= clock <= clock_band[1]:
        raise CadError("cad: clock nominal lies outside source limits")
    values["clock_deg"] = clock
    values["clock_min_deg"], values["clock_max_deg"] = clock_band
    # The index check is symmetric about the nominal: the nearer limit.
    values["clock_tolerance_deg"] = min(clock - clock_band[0], clock_band[1] - clock)
    # The open flat runs out through the cut end: a second crossing centred on
    # the end must meet the first, at the longest cut and earliest start.
    reach = values["length_max_mm"] - values["handwheel_station_min_mm"]
    if reach > 1.5 * cutter:
        raise CadError(
            "process.flat_cutter_dia_mm: two crossings cannot open the handwheel flat"
        )

    # --- Nut: axis +Y, seat face y = 0 facing -Y, head face y = flange. ------
    seat = feature("nut_seat_face", "face", _NUT)
    if seat.get("normal") != [0, -1, 0]:
        raise CadError("cad.nut_seat_face: expected the seat face along -Y")
    nominal(seat, "length", "nut_length")
    for key in ("supplied_length", "spigot_length", "spigot_dia", "full_thread_min"):
        values[f"nut_{key}_mm"] = _positive(seat.get(key), f"cad.nut_seat_face.{key}")
    values["nut_note"] = _string(seat.get("note"), "cad.nut_seat_face.note")
    if not math.isclose(
        values["nut_supplied_length_mm"] - values["nut_spigot_length_mm"],
        values["nut_length_mm"],
    ):
        raise CadError(
            "cad.nut_seat_face: facing the spigot off does not give the length"
        )
    flange = feature("nut_flange", "face", _NUT)
    nominal(flange, "thickness", "nut_flange_thickness")
    nominal(flange, "dia", "nut_flange_dia")
    nominal(feature("nut_body", "face", _NUT), "dia", "nut_body_dia")
    holes = feature("nut_holes", "hole", _NUT)
    nominal(holes, "dia", "nut_hole_dia")
    values["nut_pcd_reference_mm"] = _positive(
        holes.get("pcd_reference"), "cad.nut_holes.pcd_reference"
    )
    csk = feature("nut_countersinks", "countersink", _NUT)
    nominal(csk, "dia", "csk_dia")
    values["csk_angle_deg"] = _positive(
        csk.get("angle_deg"), "cad.nut_countersinks.angle_deg"
    )
    values["csk_cutter"] = _string(csk.get("cutter"), "cad.nut_countersinks.cutter")
    cutter_max = _positive(
        csk.get("cutter_dia_max"), "cad.nut_countersinks.cutter_dia_max"
    )
    if cutter_max < values["csk_dia_max_mm"]:
        raise CadError("cad.nut_countersinks: the cutter cannot reach the mouth")
    # tool_sizing: the cutter must reach the largest mouth and stay within
    # the drawing's cutter maximum (its cone would otherwise reach the body).
    values["csk_cutter_band_mm"] = [values["csk_dia_max_mm"], cutter_max]
    values["csk_wall_note"] = _string(
        csk.get("wall_note"), "cad.nut_countersinks.wall_note"
    )
    count = _positive(csk.get("count"), "cad.nut_countersinks.count")
    if count != holes.get("count"):
        raise CadError("cad: countersink and hole counts disagree")
    values["csk_count"] = int(count)

    stock = _positive(
        parameters.get("screw_stock_length_mm"), "process.screw_stock_length_mm"
    )
    if not math.isclose(stock, values["stock_length_mm"]):
        raise CadError("process.screw_stock_length_mm: not the supplied length")
    # Saw: the piece kept from the NEAR END is the cut plus a milling
    # allowance, marked from the NEAR END by stepping a rule twice.
    allowance = _positive(
        parameters.get("saw_allowance_mm"), "process.saw_allowance_mm"
    )
    values["saw_piece_mm"] = length + allowance
    if values["saw_piece_mm"] >= stock:
        raise CadError("process.saw_allowance_mm: the screw is too short for the cut")
    rule = _positive(parameters.get("rule_mm"), "process.rule_mm")
    values["saw_rule_step_mm"] = values["saw_piece_mm"] - rule
    if not 0 < values["saw_rule_step_mm"] <= rule:
        raise CadError("process.rule_mm: two steps of the rule must reach the mark")
    # Cut end to length: vise jaw span along the screw from the NEAR END, the
    # sawn end the overhang past the right jaw side (milling_deflection beam).
    overhang = _positive(parameters.get("cut_overhang_mm"), "process.cut_overhang_mm")
    jaw = _positive(parameters.get("vise_jaw_width_mm"), "process.vise_jaw_width_mm")
    values["vise_jaw_right_mm"] = values["saw_piece_mm"] - overhang
    values["vise_jaw_left_mm"] = values["vise_jaw_right_mm"] - jaw
    if values["vise_jaw_left_mm"] <= 0:
        raise CadError("process.cut_overhang_mm: the screw does not span the jaws")
    # Far-end crossings measured back from the cut end at the nominal length;
    # the traveler prints X −(L − centre) against the measured L.
    for name in ("far_kp08", "handwheel"):
        values[f"{name}_from_cut_mm"] = length - values[f"{name}_centre_mm"]
    # The cut-end KP08 flat's edge nearest the cut end: its farthest point
    # from the dividing-head jaws (milling_deflection station).
    values["far_kp08_outer_from_cut_mm"] = (
        length - values["far_kp08_station_mm"] - values["flat_length_mm"]
    )
    return CadData(
        values,
        StockRequirement("mm", (StockAxis("length", "screw_stock_length_mm", length),)),
        path.resolve(),
    )
