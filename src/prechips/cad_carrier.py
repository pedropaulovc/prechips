"""Bindings for the released harmonic oblique-trammel carrier (MHA-CH-06-TL-21)."""

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
    _shorthand,
    _string,
)

# Manifest feature -> sheet 2 hole-table tag. The v49 export holds exactly
# these: the four reamed pin holes, the tapped holes and the HUB tap that
# TL-00 step 10 drills at assembly.
_PINS = {
    "pin_hole_a1": "A1",
    "pin_hole_b1": "B1",
    "pin_hole_a2": "A2",
    "pin_hole_b2": "B2",
}
_TAPS = {
    "cl_tap_1": ("CL", "clamp"),
    "cr_tap_1": ("CR", "clamp"),
    "riser_tap_1": ("R1", "riser"),
    "riser_tap_2": ("R2", "riser"),
    "riser_tap_3": ("R3", "riser"),
    "riser_tap_4": ("R4", "riser"),
    "lever_tap_1": ("L1", "lever"),
    "lever_tap_2": ("L2", "lever"),
}
_HUB = "hub_tap_1"
_FACES = ("top_face", "bottom_face")
# Holes located from the lower-left plate corner itself; the rest are
# parented to A1 (sheet 2 note 2: from A1 in X, from the A1-B1 line in Y).
_CORNER = ("pin_hole_a1", "lever_tap_1", "lever_tap_2")
# The sheet prints three-place inches; a recomputed corner coordinate may
# differ from its printed value by half the last place.
_PRINTED_MM = 0.0005 * 25.4


def load_carrier(path: Path, parameters: dict) -> CadData:
    """Bind the plate envelope, the corner-frame hole table and its limits."""
    raw, values, features = _harmonic_manifest(
        path, "ch-rocker-arm-tl-oblique-carrier", "harmonic_carrier"
    )
    _model_frame(raw)
    expected = {*_FACES, *_PINS, *_TAPS, _HUB}
    if set(features) != expected:
        raise CadError(
            "cad.features: expected exactly "
            + ", ".join(sorted(expected))
            + f"; got {', '.join(sorted(features))}"
        )

    def feature(name: str) -> dict:
        item = features[name]
        if not isinstance(item, dict) or item.get("frame") != "model":
            raise CadError(f"cad.features.{name}: missing model-frame feature")
        return item

    # Model X runs along the 20.5 in length (plate centred on X0), model Y up
    # through the plate from the bottom face to the top face at Y0, and model
    # Z across the width (sheet Y = -model Z from the A1-B1 line).
    top = feature("top_face")
    bottom = feature("bottom_face")
    for name, item, normal, level in (
        ("top_face", top, [0, 1, 0], 0.0),
        ("bottom_face", bottom, [0, -1, 0], None),
    ):
        plane = item.get("plane")
        if (
            item.get("kind") != "face"
            or item.get("normal") != normal
            or not isinstance(plane, dict)
            or plane.get("axis") != "y"
        ):
            raise CadError(f"{name}: expected a model Y plane facing {normal}")
        if level is not None and _number(plane.get("value"), f"{name}.plane") != level:
            raise CadError(f"{name}: expected the top face at model Y0")
    envelope = []
    for key, item, field, where in (
        ("length", top, "length", "top_face"),
        ("width", top, "width", "top_face"),
        ("thickness", bottom, "height", "bottom_face"),
    ):
        band = _band(item, field, where)
        _inch_limits(values, key, band)
        nominal = _positive(item.get(f"{field}_nominal"), f"{where}.{field}_nominal")
        if not band[0] <= nominal <= band[1]:
            raise CadError(f"{where}.{field}_nominal: outside {field} band")
        values[f"{key}_mm"] = nominal
        envelope.append(StockAxis(key, f"blank_{key}_in", nominal))
    floor = _number(bottom["plane"].get("value"), "bottom_face.plane")
    if not math.isclose(floor, -values["thickness_mm"], abs_tol=1e-6):
        raise CadError("bottom_face: plane disagrees with the thickness nominal")

    def hole(name: str) -> tuple[dict, float, float]:
        item = feature(name)
        at = item.get("at")
        if (
            item.get("kind") != "hole"
            or item.get("axis") != [0, -1, 0]
            or item.get("thru") is not True
            or not isinstance(at, list)
            or len(at) != 3
            or _number(at[1], f"{name}.at") != 0
        ):
            raise CadError(f"{name}: expected a through hole down from the top face")
        return item, _number(at[0], f"{name}.at"), _number(at[2], f"{name}.at")

    # The corner frame: the lever holes and A1 are tabled from the lower-left
    # corner, so they fix it; every hole then reads as the sheet 2 table does.
    # The plate is centred on model X0; the corner holes agree on the bottom
    # edge within the sheet's printed rounding.
    _, a1_x, a1_z = hole("pin_hole_a1")
    corners = []
    for name in _CORNER:
        item, x, z = hole(name)
        if item.get("parent") is not None or item.get("height_from") is not None:
            raise CadError(f"{name}: expected a corner-located hole")
        station = _positive(item.get("station_nominal"), f"{name}.station_nominal")
        height = _positive(item.get("height_nominal"), f"{name}.height_nominal")
        corners.append((x - station, z + height))
    left = -values["length_mm"] / 2
    bottom_z = sorted(z for _, z in corners)[1]
    if not all(
        math.isclose(x, left, abs_tol=_PRINTED_MM)
        and math.isclose(z, bottom_z, abs_tol=_PRINTED_MM)
        for x, z in corners
    ):
        raise CadError(
            "cad.features: corner-located holes disagree on the plate corner"
        )

    def corner(x: float, z: float) -> tuple[float, float]:
        return x - left, bottom_z - z

    rows: list[list[str]] = []
    points: dict[str, tuple[float, float]] = {}
    tolerances: list[float] = []

    def located(name: str, tag: str, item: dict, x: float, z: float) -> None:
        cx, cy = corner(x, z)
        if not (0 < cx < values["length_mm"] and 0 < cy < values["width_mm"]):
            raise CadError(f"{name}: hole centre off the plate")
        station = _band(item, "station", name)
        parented = name not in _CORNER
        if parented and item.get("parent") != "pin_hole_a1":
            raise CadError(f"{name}: expected a hole located from A1")
        relative_x, relative_y = (x - a1_x, a1_z - z) if parented else (cx, cy)
        if not station[0] <= relative_x <= station[1]:
            raise CadError(f"{name}.at: station outside its station band")
        tolerances.append((station[1] - station[0]) / 2)
        values[f"{tag.lower()}_station_band_mm"] = list(station)
        points[tag] = (cx / 25.4, cy / 25.4)
        if name == "pin_hole_b1":
            # B1 defines the A1-B1 axis line: no height of its own.
            if "height" in item.get("requirements", []) or z != a1_z:
                raise CadError("pin_hole_b1: expected B1 on the A1-B1 line")
            return
        height = _band(item, "height", name)
        if parented and item.get("height_from") != "pin_hole_a1":
            raise CadError(f"{name}: expected its height from the A1-B1 line")
        if not height[0] <= relative_y <= height[1]:
            raise CadError(f"{name}.at: height outside its height band")
        values[f"{tag.lower()}_height_band_mm"] = list(height)
        if tag not in ("A2", "B2"):
            tolerances.append((height[1] - height[0]) / 2)

    pin_dia = pin_note = None  # The four pins share one size and note.
    for name, tag in _PINS.items():
        item, x, z = hole(name)
        dia = _band(item, "dia", name)
        note = _string(item.get("note"), f"{name}.note")
        if pin_dia is None:
            pin_dia, pin_note = dia, note
        elif dia != pin_dia or note != pin_note:
            raise CadError(f"{name}: pin holes disagree on size or note")
        located(name, tag, item, x, z)
    _inch_limits(values, "pin_dia", pin_dia)

    groups: dict[str, tuple[str, tuple[float, float], float]] = {}
    for name, (tag, group) in _TAPS.items():
        item, x, z = hole(name)
        thread = _string(item.get("thread"), f"{name}.thread")
        drill = _band(item, "dia", name)
        tap_drill = _positive(item.get("tap_drill_mm"), f"{name}.tap_drill_mm")
        if not math.isclose(tap_drill, drill[0], abs_tol=0.001):
            raise CadError(f"{name}: tap drill disagrees with its drilled band")
        shared = groups.setdefault(group, (thread, drill, tap_drill))
        if shared != (thread, drill, tap_drill):
            raise CadError(f"{name}: {group} holes disagree on thread or drill")
        located(name, tag, item, x, z)
    for group, (thread, drill, _) in groups.items():
        values[f"{group}_thread"] = thread
        _inch_limits(values, f"{group}_drill", drill)

    # Sheet 2 note 2 / title block: one ±.XXX location tolerance; note 1
    # holds the outer pair's row tighter, from the A1-B1 line.
    if any(not math.isclose(t, tolerances[0], abs_tol=1e-6) for t in tolerances):
        raise CadError("cad.features: hole locations disagree on one tolerance")
    values["location_tol_in"] = tolerances[0] / 25.4
    if values["a2_height_band_mm"] != values["b2_height_band_mm"]:
        raise CadError("pin_hole_a2/b2: outer rows disagree")
    _inch_limits(values, "outer_row", tuple(values["a2_height_band_mm"]))
    values["outer_row_tol_in"] = (
        values["outer_row_max_in"] - values["outer_row_min_in"]
    ) / 2
    # A2 lies left of A1: its X from A1 as a positive distance.
    low, high = values["a2_station_band_mm"]
    values["a2_offset_band_mm"] = [-high, -low]
    _inch_limits(values, "a2_offset", (-high, -low))
    for tag in ("b1", "b2"):
        _inch_limits(values, f"{tag}_station", tuple(values[f"{tag}_station_band_mm"]))
    values["b1_station_in"] = sum(values["b1_station_band_mm"]) / 2 / 25.4
    if values["l1_station_band_mm"] != values["l2_station_band_mm"]:
        raise CadError("lever_tap_1/2: expected one lever station")
    _inch_limits(values, "l1_station", tuple(values["l1_station_band_mm"]))
    # Corner-located: A1 and the L rows, measured from ZERO END / ZERO EDGE.
    _inch_limits(values, "a1_station", tuple(values["a1_station_band_mm"]))
    for tag in ("a1", "l1", "l2"):
        _inch_limits(values, f"{tag}_row", tuple(values[f"{tag}_height_band_mm"]))
    values["relation_rows"] = _relation_rows(values)

    order = ("A1", "B1", "A2", "B2", "CL", "CR", "R1", "R2", "R3", "R4", "L1", "L2")
    bores = {tag: "ream" for tag in _PINS.values()}
    bores |= {tag: values[f"{group}_thread"] for tag, group in _TAPS.values()}
    for tag in order:
        x, y = points[tag]
        rows.append([tag, _shorthand(x, 3), _shorthand(y, 3), bores[tag]])
    values["hole_rows"] = rows
    values["hole_points_in"] = {tag: list(points[tag]) for tag in order}
    values["hole_count"] = len(order)

    hub, hub_x, hub_z = hole(_HUB)
    if any(key in hub.get("requirements", []) for key in ("station", "height")):
        raise CadError(f"{_HUB}: expected no manufactured location (made at assembly)")
    hub_thread = _string(hub.get("thread"), f"{_HUB}.thread")
    if hub_thread != values["clamp_thread"]:
        raise CadError(f"{_HUB}: expected the CL/CR thread")
    values["hub_x_in"], values["hub_y_in"] = (v / 25.4 for v in corner(hub_x, hub_z))

    material = raw.get("material")
    if not isinstance(material, dict):
        raise CadError("cad.material: expected a table")
    values["material_spec"] = _string(material.get("spec"), "cad.material.spec")

    _edge_breaks(raw, values)
    _blank_mm(values, parameters)
    _support_blocks(values, parameters)
    _strap_toes(values, parameters)
    _spacer_seat(values, parameters)
    return CadData(values, StockRequirement("in", tuple(envelope)), path.resolve())


def _support_blocks(values: dict, parameters: dict) -> None:
    """Four 1-2-3 blocks, mirrored about mid-length, each clear of every hole.

    The holes are drilled and reamed through with the plate still on the
    blocks, so a block under a hole would take the drill. Refuse any block
    whose footprint (``block_length_in`` along X, ``block_width_in`` across,
    centred on the width) reaches a hole edge, the HUB included.
    """
    keys = (
        "block_inner_offset_in",
        "block_outer_offset_in",
        "block_length_in",
        "block_width_in",
    )
    if not all(key in parameters for key in keys):
        return
    inner, outer, along, across = (
        _positive(parameters[key], f"process.{key}") for key in keys
    )
    length = values["length_mm"] / 25.4
    width = values["width_mm"] / 25.4
    middle = length / 2
    centres = [middle - outer, middle - inner, middle + inner, middle + outer]
    if not (along / 2 < centres[0] and centres[-1] + along / 2 < length):
        raise CadError("process.block_outer_offset_in: block past a plate end")
    if inner - along / 2 <= 0 or outer - inner < along:
        raise CadError("process.block_inner_offset_in: blocks overlap")
    y0, y1 = (width - across) / 2, (width + across) / 2
    holes = [
        (tag, x, y, values["pin_dia_max_in"] / 2 if tag[0] in "AB" else None)
        for tag, (x, y) in values["hole_points_in"].items()
    ]
    radius = {
        "C": values["clamp_drill_max_in"] / 2,
        "R": values["riser_drill_max_in"] / 2,
        "L": values["lever_drill_max_in"] / 2,
    }
    holes = [(tag, x, y, r or radius[tag[0]]) for tag, x, y, r in holes]
    holes.append(("HUB", values["hub_x_in"], values["hub_y_in"], radius["C"]))
    for index, centre in enumerate(centres, 1):
        x0, x1 = centre - along / 2, centre + along / 2
        for tag, x, y, r in holes:
            if x0 - r < x < x1 + r and y0 - r < y < y1 + r:
                raise CadError(
                    f"process.block_*_offset_in: block {index} "
                    f"(X {x0:.2f}–{x1:.2f}) is under hole {tag}"
                )
    values["block_x_in"] = centres
    values["block_stations"] = ", ".join(f"{x:.2f}" for x in centres)
    _beam_stations(values, centres, along)


def _beam_stations(values: dict, centres: list[float], along: float) -> None:
    """Millimetre stations along X for the plan's milling_deflection beams.

    X runs from the finished ZERO END. A strap over a block clamps both ways
    at the block's centre; a block's outer edge is the fulcrum a drill's
    thrust bends the plate over beyond it. Before the ends are squared the
    plate is the blank, trimmed equally, so its frame starts at the blank's
    left end. Hole groups are the hole table's X, by thread or bore.
    """
    mm = [x * 25.4 for x in centres]
    values["end_block_x_mm"] = [mm[0], mm[3]]
    values["inner_block_x_mm"] = [mm[1], mm[2]]
    values["block_span_mm"] = [
        (centres[0] - along / 2) * 25.4,
        (centres[3] + along / 2) * 25.4,
    ]
    if "blank_length_mm" in values:
        trim = (values["blank_length_mm"] - values["length_mm"]) / 2
        values["end_block_blank_x_mm"] = [mm[0] + trim, mm[3] + trim]
        # Before the ends are squared there is no ZERO END: the blocks go
        # down from the sawn left end.
        values["block_blank_stations"] = ", ".join(
            f"{x + trim / 25.4:.2f}" for x in centres
        )
    points = values["hole_points_in"]
    for key, prefix in (
        ("pin_x_mm", "AB"),
        ("clamp_x_mm", "C"),
        ("riser_x_mm", "R"),
        ("lever_x_mm", "L"),
    ):
        values[key] = [x * 25.4 for tag, (x, _) in points.items() if tag[0] in prefix]
    values["hole_x_mm"] = [x * 25.4 for x, _ in points.values()]


def _spacer_seat(values: dict, parameters: dict) -> None:
    """The TL-VN-78 spacer seats on each pin hole's broken underside edge.

    The drawing has no underside chamfer, only the title block's edge break
    (owner ruling 2026-11-13). The spacer's OD is authored: the largest bore
    plus the largest break either side must stay inside it.
    """
    if "spacer_seat_dia_in" not in parameters:
        return
    seat = _positive(parameters["spacer_seat_dia_in"], "process.spacer_seat_dia_in")
    mouth = values["pin_dia_max_in"] + 2 * values["chamfer_max_in"]
    if mouth >= seat:
        raise CadError("process.spacer_seat_dia_in: the edge break reaches the seat")
    values["spacer_seat_margin_in"] = (seat - mouth) / 2


_RELATED = ("B1", "A2", "B2", "CL", "CR", "R1", "R2", "R3", "R4")


def _span(band: list[float]) -> str:
    low, high = (value / 25.4 for value in band)
    return f"{_shorthand(low, 3)}–{_shorthand(high, 3)}"


def _relation_rows(values: dict) -> list[list[str]]:
    """Sheet 2 note 2 as acceptance limits: X from A1, Y from the A1-B1 line.

    A2 lies left of A1, so its X prints as a distance to the left. B1 sets
    the line and has no row of its own.
    """
    rows = []
    for tag in _RELATED:
        key = tag.lower()
        x = _span(values[f"{key}_station_band_mm"])
        if tag == "A2":
            x = f"{_span(values['a2_offset_band_mm'])} left"
        y = _span(values[f"{key}_height_band_mm"]) if tag != "B1" else "sets the line"
        rows.append([tag, x, y])
    return rows


def _strap_toes(values: dict, parameters: dict) -> None:
    """Every strap toe lands on a block, so no clamp bends the overhang.

    ``strap_toe_in`` is the toe's centre in from a long edge. Blocks are
    centred on the width, so the toe must fall inside a block's span across.
    """
    if "strap_toe_in" not in parameters or "block_width_in" not in parameters:
        return
    toe = _positive(parameters["strap_toe_in"], "process.strap_toe_in")
    across = _positive(parameters["block_width_in"], "process.block_width_in")
    width = values["width_mm"] / 25.4
    if not (width - across) / 2 < toe < (width + across) / 2:
        raise CadError("process.strap_toe_in: strap toe outside the blocks")
