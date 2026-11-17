"""Static workpiece bending screen for declared milling and drilling cuts.

Every mill or drill-press setup declares how the part is held as a beam and
every spindle operation its cuts. The handbook mean cutting force (unit power ×
removal rate ÷ cutting speed) or drill thrust loads an Euler–Bernoulli beam at
each declared cut station: a cantilever from the nearer clamp edge, two pinned
supports (inside the span or on an overhang beyond one), or a stated rigid seat
(no bending). Coefficients, authored force ratios and limits live in
turning.toml beside the turning data. The spindle is vertical (machine Z). This
is a stiffness screen at the cut, not predicted dimensional error, chatter,
clamp slip or machine compliance.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from prechips import shop, vise
from prechips.checks import CheckError
from prechips.turning import (
    INCH_MM,
    LBF_N,
    TurningError,
    cutting_force_n,
    table_factor,
)

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_AXES = ("x", "y", "z")
_SPINDLE = "z"
_MILLING = ("side", "end", "face", "slot")
_HELICAL = ("side", "slot")
_THRUST = ("plunge", "drill")
_HOLDS = {
    "cantilever": {"clamp_mm", "section_mm"},
    "between": {"supports_mm", "section_mm"},
    "solid": {"seat", "seat_mm"},
}
# A cantilever in a milling vise names which extent end the vise's left
# overhang is measured from, and which hold when the setup re-grips.
_VISE_LINK = {"vise_left", "vise_hold"}
_CUT_KEYS = {
    "name",
    "kind",
    "phase",
    "material",
    "cutter_dia_mm",
    "flutes",
    "axial_doc_mm",
    "radial_woc_mm",
    "feed_per_tooth_mm",
    "rpm",
    "feed_mm_min",
    "stations_mm",
    "traverse_mm",
    "max_deflection_mm",
    "finish_cut",
    "finish_stock_mm",
}


def section_inertia_mm4(section: dict, bending: str) -> float:
    """Second moment of area for bending along ``bending`` (mm^4).

    Round: pi*D^4/64. Rectangle: width * depth^3 / 12, depth along ``bending``.
    """
    if "diameter" in section:
        return math.pi * section["diameter"] ** 4 / 64
    (width,) = (size for axis, size in section.items() if axis != bending)
    return width * section[bending] ** 3 / 12


def cantilever_mm(force_n: float, length_mm: float, rigidity: float) -> float:
    """Deflection under an end load L from a fixed clamp: F*L^3/(3EI)."""
    return force_n * length_mm**3 / (3 * rigidity)


def pinned_mm(force_n: float, a_mm: float, b_mm: float, rigidity: float) -> float:
    """Deflection under a load a and b from two pinned supports: F*a^2*b^2/(3EI*l)."""
    return force_n * a_mm**2 * b_mm**2 / (3 * rigidity * (a_mm + b_mm))


def overhang_mm(force_n: float, c_mm: float, span_mm: float, rigidity: float) -> float:
    """Deflection under a load c beyond one of two pinned supports: F*c^2*(c+l)/(3EI)."""
    return force_n * c_mm**2 * (c_mm + span_mm) / (3 * rigidity)


def milling_force_n(
    unit_power: float,
    feed_factor: float,
    wear: float,
    woc_mm: float,
    doc_mm: float,
    feed_per_tooth_mm: float,
    flutes: int,
    cutter_dia_mm: float,
) -> float:
    """Mean tangential force: unit power × removal rate ÷ cutting speed.

    Q = ft*nt*N*w*d in^3/min at V = pi*D*N/12 ft/min, so the mean chip area
    Q/(12*V) = w*d*ft*nt/(pi*D) in^2 and Ft = 396000*Kp*C*W*w*d*ft*nt/(pi*D)
    lbf; rpm cancels.
    """
    chip_area = (
        (woc_mm / INCH_MM)
        * (doc_mm / INCH_MM)
        * (feed_per_tooth_mm / INCH_MM)
        * flutes
        / (math.pi * cutter_dia_mm / INCH_MM)
    )
    return cutting_force_n(unit_power, feed_factor, wear, chip_area)


def drill_thrust_n(
    kd: float,
    feed_factor: float,
    diameter_factor: float,
    chisel_b: float,
    chisel_j: float,
    wear: float,
    dia_mm: float,
) -> float:
    """Handbook drill thrust T = 2*Kd*Ff*FT*B*W + Kd*D^2*J*W (lb, D in)."""
    diameter = dia_mm / INCH_MM
    lips = 2 * kd * feed_factor * diameter_factor * chisel_b * wear
    chisel = kd * diameter**2 * chisel_j * wear
    return (lips + chisel) * LBF_N


def _number(value: object, where: str) -> float:
    if type(value) not in (int, float):
        raise CheckError(f"{where}: expected a finite number")
    try:
        number = float(value)
    except OverflowError:  # TOML integers are unbounded
        number = math.inf
    if not math.isfinite(number):
        raise CheckError(f"{where}: expected a finite number")
    return number


def _positive(value: object, where: str) -> float:
    number = _number(value, where)
    if number <= 0:
        raise CheckError(f"{where}: expected a positive number")
    return number


def _fields(table: dict, required: set[str], allowed: set[str], where: str) -> None:
    unknown = table.keys() - allowed
    if unknown:
        raise CheckError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
    missing = required - table.keys()
    if missing:
        raise CheckError(f"{where}: missing {', '.join(sorted(missing))}")


def _span(value: object, where: str) -> tuple[float, float]:
    """One station, or an ascending [start, end] pair along the beam axis."""
    if isinstance(value, list):
        if len(value) != 2:
            raise CheckError(f"{where}: expected a station or [start, end]")
        low, high = (_number(item, where) for item in value)
        if low > high:
            raise CheckError(f"{where}: expected [start, end] with start <= end")
        return low, high
    station = _number(value, where)
    return station, station


def _section(value: object, axis: str, where: str) -> dict:
    across = [other for other in _AXES if other != axis]
    if not isinstance(value, dict) or value.keys() not in (
        {"diameter"},
        set(across),
    ):
        raise CheckError(
            f"{where}: expected {{ diameter }} or the two sizes across the beam, "
            f"{{ {across[0]}, {across[1]} }}"
        )
    return {key: _positive(size, f"{where}.{key}") for key, size in value.items()}


def _beam(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise CheckError(f'{where}: expected a table or "other"')
    hold = value.get("hold")
    if not isinstance(hold, str) or hold not in _HOLDS:
        raise CheckError(f"{where}.hold: expected cantilever, between or solid")
    keys = {"axis", "hold", "extent_mm"} | _HOLDS[hold]
    _fields(value, keys, keys | (_VISE_LINK if hold == "cantilever" else set()), where)
    axis = value["axis"]
    if axis not in _AXES:
        raise CheckError(f"{where}.axis: expected x, y or z")
    extent = _span(value["extent_mm"], f"{where}.extent_mm")
    if extent[0] == extent[1]:
        raise CheckError(f"{where}.extent_mm: expected the part's [start, end]")
    beam = {"axis": axis, "hold": hold, "extent": extent}
    key = {"cantilever": "clamp_mm", "between": "supports_mm", "solid": "seat_mm"}[hold]
    stations = _span(value[key], f"{where}.{key}")
    if not extent[0] <= stations[0] <= stations[1] <= extent[1]:
        raise CheckError(f"{where}.{key}: must lie within extent_mm")
    if hold == "between" and stations[0] == stations[1]:
        raise CheckError(f"{where}.supports_mm: expected two distinct supports")
    beam["stations"] = stations
    if hold == "solid":
        seat = value["seat"]
        if not isinstance(seat, str) or not seat.strip():
            raise CheckError(f"{where}.seat: expected the rigid seat, stated")
        beam["seat"] = seat
    else:
        beam["section"] = _section(value["section_mm"], axis, f"{where}.section_mm")
    if "vise_left" in value:
        if value["vise_left"] not in ("start", "end", "other"):
            raise CheckError(f"{where}.vise_left: expected start, end or other")
        beam["vise_left"] = value["vise_left"]
    if "vise_hold" in value:
        index = value["vise_hold"]
        if beam.get("vise_left") not in ("start", "end"):
            raise CheckError(f"{where}.vise_hold: requires vise_left start or end")
        if type(index) is not int or index < 1:
            raise CheckError(f"{where}.vise_hold: expected a hold number from 1")
        beam["vise_hold"] = index
    return beam


def _vise_link(beam: dict, holds: list[dict], required: bool, where: str) -> None:
    """Refuse a cantilever clamp that is not the grip its vise hold describes.

    ``vise_left`` names the extent end the hold's left overhang is measured
    from; the clamp is then the part's span between the jaws.
    """
    mapping = beam.get("vise_left")
    if not holds:
        if mapping is not None:
            raise CheckError(f"{where}.vise_left: the setup declares no vise hold")
        return
    if beam["hold"] != "cantilever":
        return
    if mapping is None:
        if required:
            raise CheckError(
                f'{where}: missing vise_left ("start" or "end": the extent end at '
                'the vise hold\'s left overhang; "other" when the beam does not '
                "run along the jaws)"
            )
        return
    if mapping == "other":
        return
    index = beam.get("vise_hold")
    if index is None and len(holds) > 1:
        raise CheckError(f"{where}: missing vise_hold, the number of its vise hold")
    index = index or 1
    if index > len(holds):
        raise CheckError(f"{where}.vise_hold: the setup has {len(holds)} vise holds")
    held = holds[index - 1]
    left, right = vise.overhangs(held, where)
    width = shop.fact(held["vise"], "jaw_width_mm")
    start, end = beam["extent"]
    length = end - start
    along = held["along_jaws_mm"]
    if abs(length - along) > vise.ROUNDING_MM:
        raise CheckError(
            f"{where}.extent_mm: {length:g} mm long, but vise hold {index} has "
            f"{along:g} mm along the jaws"
        )
    # From the part's left end the jaws grip [left, left + width] of it.
    near, far = max(0.0, left), min(length, left + width)
    grip = (
        (start + near, start + far) if mapping == "start" else (end - far, end - near)
    )
    if any(
        abs(declared - gripped) > vise.ROUNDING_MM
        for declared, gripped in zip(beam["stations"], grip, strict=True)
    ):
        low, high = beam["stations"]
        raise CheckError(
            f"{where}.clamp_mm: {low:g}..{high:g} mm, but vise hold {index} grips "
            f"{grip[0]:g}..{grip[1]:g} mm (overhangs {left:g} and {right:g} mm, "
            f"jaw width {width:g} mm, its left overhang at the extent {mapping})"
        )


def _axes(beam: dict, kind: str) -> list[str]:
    """Every axis across the beam that the cut loads; none for thrust along it.

    A milling cut always loads both: the cross-spindle resultant in each
    horizontal axis and helix lift or end-tooth push along z. Drill and plunge
    thrust is along z, which compresses a beam along z instead of bending it.
    """
    loaded = [_SPINDLE] if kind in _THRUST else list(_AXES)
    return [axis for axis in loaded if axis != beam["axis"]]


def _feed_per_tooth(cut: dict, flutes: int, operation: dict, where: str) -> float:
    chip_load = operation.get("chip_load_mm_per_tooth")
    if chip_load is not None:
        # The operation prints the feed its shared setting calculates.
        if {"rpm", "feed_mm_min"} & cut.keys():
            raise CheckError(
                f"{where}: the operation's setting gives {chip_load:g} mm/tooth; "
                "declare feed_per_tooth_mm or no feed, not rpm with feed_mm_min"
            )
        feed = _positive(
            cut.get("feed_per_tooth_mm", chip_load), f"{where}.feed_per_tooth_mm"
        )
        if feed != chip_load:
            raise CheckError(
                f"{where}.feed_per_tooth_mm: {feed:g} disagrees with the "
                f"operation's setting, {chip_load:g} mm/tooth"
            )
        return feed
    if "feed_per_tooth_mm" in cut:
        if {"rpm", "feed_mm_min"} & cut.keys():
            raise CheckError(
                f"{where}: declare feed_per_tooth_mm or rpm with feed_mm_min, not both"
            )
        return _positive(cut["feed_per_tooth_mm"], f"{where}.feed_per_tooth_mm")
    if not {"rpm", "feed_mm_min"} <= cut.keys():
        raise CheckError(f"{where}: missing feed_per_tooth_mm or rpm with feed_mm_min")
    rpm = _positive(cut["rpm"], f"{where}.rpm")
    # The printed spindle speed and the analysed one must not drift apart.
    op_rpm = operation.get("rpm")
    if op_rpm is not None and rpm != op_rpm:
        raise CheckError(
            f"{where}.rpm: {rpm:g} disagrees with the operation's {op_rpm} rpm"
        )
    return _positive(cut["feed_mm_min"], f"{where}.feed_mm_min") / (rpm * flutes)


def _cutter(
    cut: dict, kind: str, operation: dict, where: str
) -> tuple[float, int, float]:
    """Cutter diameter, flutes and feed per tooth, validated for every cut.

    An operation whose shared setting declares a chip load carries that load
    and its flutes; a cut takes them from it or must restate them exactly.
    """
    diameter = _positive(cut["cutter_dia_mm"], f"{where}.cutter_dia_mm")
    setting_flutes = operation.get("flutes")
    flutes = cut.get("flutes", setting_flutes)
    if flutes is None:
        raise CheckError(f"{where}: missing flutes")
    if type(flutes) is not int or flutes < 1:
        raise CheckError(f"{where}.flutes: expected a positive integer")
    if setting_flutes is not None and flutes != setting_flutes:
        raise CheckError(
            f"{where}.flutes: {flutes} disagrees with the operation's setting, "
            f"{setting_flutes} flutes"
        )
    feed = _feed_per_tooth(cut, flutes, operation, where)
    if kind in _THRUST and {"axial_doc_mm", "radial_woc_mm"} & cut.keys():
        raise CheckError(
            f"{where}: {kind} thrust takes no axial_doc_mm or radial_woc_mm"
        )
    return diameter, flutes, feed


def _axial_ratio(kind: str, tool: dict | None, config: dict) -> tuple[float, str]:
    """Axial ratio to the tangential force, and where it came from.

    A tool's stated ``axial_ratio`` wins; a stated ``helix_deg`` gives
    tan(helix) for the helix lift of side and slot cuts; otherwise the
    configured default.
    """
    if tool is not None and "axial_ratio" in tool:
        return tool["axial_ratio"], f"tool {tool['id']!r} axial_ratio"
    if tool is not None and "helix_deg" in tool and kind in _HELICAL:
        helix = tool["helix_deg"]
        return math.tan(math.radians(helix)), f"tan {helix:g}° helix of {tool['id']!r}"
    return config["milling"]["axial_ratio"], "configured axial_ratio"


def _forces(
    cut: dict,
    kind: str,
    material: tuple[str, dict],
    config: dict,
    cutter: tuple[float, int, float],
    tool: dict | None,
    where: str,
) -> dict:
    """Force (N) and its description for each bending direction class."""
    diameter, flutes, feed = cutter
    name, material = material
    if kind in _THRUST:
        if "drill_kd" not in material:
            raise CheckError(f"{where}: material {name!r} has no drill_kd")
        drilling = config["drilling"]
        thrust = drill_thrust_n(
            material["drill_kd"],
            table_factor(
                feed * flutes / INCH_MM,
                drilling["feed_factors"],
                "feed",
                "in/rev",
                "drilling feed-factor",
            ),
            table_factor(
                diameter / INCH_MM,
                drilling["diameter_factors"],
                "diameter",
                "in",
                "drill diameter-factor",
            ),
            drilling["chisel_thrust_b"],
            drilling["chisel_thrust_j"],
            drilling["wear"],
            diameter,
        )
        return {_SPINDLE: (thrust, f"drill thrust {thrust:.3g} N")}
    for key in ("axial_doc_mm", "radial_woc_mm"):
        if key not in cut:
            raise CheckError(f"{where}: missing {key}")
    doc = _positive(cut["axial_doc_mm"], f"{where}.axial_doc_mm")
    woc = _positive(cut["radial_woc_mm"], f"{where}.radial_woc_mm")
    if kind == "slot" and not math.isclose(woc, diameter, rel_tol=0, abs_tol=1e-6):
        raise CheckError(f"{where}: a slot cut is cutter_dia_mm wide")
    if woc > diameter + 1e-6:
        raise CheckError(f"{where}.radial_woc_mm: exceeds cutter_dia_mm")
    milling = config["milling"]
    tangential = milling_force_n(
        material["unit_power_hp_min_per_in3"],
        table_factor(
            feed / INCH_MM,
            config["force"]["feed_factors"],
            "feed",
            "in/tooth",
            "feed-factor",
        ),
        milling["face_wear" if kind == "face" else "wear"],
        woc,
        doc,
        feed,
        flutes,
        diameter,
    )
    across = tangential * math.hypot(1, milling["radial_ratio"])
    ratio, source = _axial_ratio(kind, tool, config)
    along = tangential * ratio
    along_text = (
        f"axial force {along:.3g} N (tangential {tangential:.3g} N × "
        f"{ratio:.3g}, {source})"
    )
    across_text = (
        f"cross-spindle force {across:.3g} N (tangential {tangential:.3g} N × "
        f"√(1 + radial_ratio {milling['radial_ratio']:g}²))"
    )
    return {_SPINDLE: (along, along_text), "across": (across, across_text)}


def _deflection(beam: dict, station: float, force: float, rigidity: float):
    """Deflection (mm) at ``station`` and the governing span's description."""
    low, high = beam["stations"]
    if beam["hold"] == "solid":
        if not low <= station <= high:
            raise CheckError(
                f"station {station:g} mm is off the stated seat {low:g}..{high:g} mm"
            )
        return 0.0, f"solid on {beam['seat']}"
    if beam["hold"] == "cantilever":
        if low <= station <= high:
            return 0.0, f"inside the clamp {low:g}..{high:g} mm"
        edge = high if station > high else low
        length = abs(station - edge)
        return (
            cantilever_mm(force, length, rigidity),
            f"cantilever {length:.6g} mm from the clamp edge at {edge:.6g} mm",
        )
    span = high - low
    if not low <= station <= high:
        edge = high if station > high else low
        overhang = abs(station - edge)
        text = (
            f"overhang {overhang:.6g} mm beyond the support at {edge:.6g} mm of a "
            f"pinned span {span:.6g} mm"
        )
        return overhang_mm(force, overhang, span, rigidity), text
    a, b = station - low, high - station
    text = (
        f"pinned span {span:.6g} mm between supports at {low:.6g} and "
        f"{high:.6g} mm, load {a:.6g} mm from the first"
    )
    return pinned_mm(force, a, b, rigidity), text


def _stations(cut: dict, beam: dict, where: str) -> list[float]:
    """Evaluation points: declared stations, or a traverse's worst candidates.

    Along a traverse, cantilever and overhang bending grow toward its ends and
    pinned-span bending peaks at mid-span, so its ends and any mid-span point
    inside it bound the whole pass.
    """
    declared = {"stations_mm", "traverse_mm"} & cut.keys()
    if len(declared) != 1:
        raise CheckError(
            f"{where}: declare stations_mm (points) or traverse_mm ([start, end] "
            "travel along the beam), exactly one"
        )
    if "traverse_mm" in cut:
        start, end = _span(cut["traverse_mm"], f"{where}.traverse_mm")
        stations = [start, end]
        middle = sum(beam["stations"]) / 2
        if beam["hold"] == "between" and start < middle < end:
            stations.append(middle)
        key = "traverse_mm"
    else:
        stations = cut["stations_mm"]
        stations = stations if isinstance(stations, list) else [stations]
        if not stations:
            raise CheckError(f"{where}.stations_mm: expected at least one station")
        key = "stations_mm"
        stations = [_number(station, f"{where}.{key}") for station in stations]
    extent = beam["extent"]
    for station in stations:
        if not extent[0] <= station <= extent[1]:
            raise CheckError(
                f"{where}.{key}: {station:g} mm lies off the part "
                f"{extent[0]:g}..{extent[1]:g} mm"
            )
    return stations


def _limits(
    cut: dict, phase: str, axes: list[str], config: dict, later: list, where: str
) -> dict[str, tuple[float, str] | None]:
    """Each loaded axis's limit and its description; None where a rough cut
    passes through the part.

    A rough cut that names the finish cut following it and the stock that cut
    leaves along each loaded axis is compared with that stock instead of the
    rough limit; nothing is inferred from the finish cut or from prose.
    """
    limit = config["milling"][f"{phase}_mm"]
    tighter = None
    if "max_deflection_mm" in cut:
        tighter = _positive(cut["max_deflection_mm"], f"{where}.max_deflection_mm")
    declared = {"finish_cut", "finish_stock_mm"} & cut.keys()
    if not declared:
        if tighter is not None:
            limit = min(limit, tighter)
        return {axis: (limit, f"{phase} limit {limit:g} mm") for axis in axes}
    if phase != "rough":
        raise CheckError(
            f"{where}: only a rough cut declares finish_cut and finish_stock_mm"
        )
    if len(declared) == 1:
        raise CheckError(f"{where}: declare finish_cut with finish_stock_mm")
    finish = cut["finish_cut"]
    if not any(
        isinstance(other, dict)
        and other.get("name") == finish
        and other.get("phase") == "finish"
        for other in later
    ):
        raise CheckError(f"{where}.finish_cut: {finish!r} names no later finish cut")
    stock = cut["finish_stock_mm"]
    if not isinstance(stock, dict) or stock.keys() != set(axes):
        raise CheckError(
            f"{where}.finish_stock_mm: expected {{ {', '.join(axes)} }}: the stock "
            f'{finish!r} leaves along each loaded axis, or "through" where this '
            "cut passes through the part"
        )
    limits = {}
    for axis in axes:
        if stock[axis] == "through":
            limits[axis] = None
            continue
        amount = _positive(stock[axis], f"{where}.finish_stock_mm.{axis}")
        text = f"finish stock {amount:g} mm that {finish!r} leaves along {axis}"
        if tighter is not None and tighter < amount:
            amount, text = tighter, f"max_deflection_mm {tighter:g} mm"
        limits[axis] = (amount, text)
    return limits


def _check_cut(
    cut: dict, beam: dict, operation: dict, context: dict, where: str
) -> None:
    config = context["config"]
    _fields(cut, {"name", "kind", "phase", "cutter_dia_mm"}, _CUT_KEYS, where)
    kind = cut["kind"]
    if kind not in _MILLING + _THRUST:
        raise CheckError(f"{where}.kind: expected {', '.join(_MILLING + _THRUST)}")
    phase = cut["phase"]
    if phase not in ("rough", "finish"):
        raise CheckError(f"{where}.phase: expected rough or finish")
    name = cut.get("material", context["material"])
    if name is None:
        raise CheckError(f"{where}: missing material (or the plan's milling_material)")
    material = config["materials"].get(name) if isinstance(name, str) else None
    if material is None:
        raise CheckError(
            f"{where}.material: {name!r} must select a configured material"
        )
    axes = _axes(beam, kind)
    # A seat only takes a downward push; every milling cut also loads it
    # across the spindle, and side and slot cuts lift.
    if beam["hold"] == "solid" and kind not in _THRUST:
        raise CheckError(
            f"{where}: a solid seat resists only the downward push of a drill or "
            f"plunge, not a {kind} cut's cross-spindle force or lift; declare a "
            "cantilever or between beam for this cut"
        )
    stations = _stations(cut, beam, where)
    order = context["cuts"]
    position = next(index for index, other in enumerate(order) if other is cut)
    limits = _limits(cut, phase, axes, config, order[position + 1 :], where)
    cutter = _cutter(cut, kind, operation, where)
    if not axes:
        # Thrust along an upright beam compresses it; no force is needed.
        return
    tool = context["tools"].get(operation.get("tool"))
    forces = _forces(cut, kind, (name, material), config, cutter, tool, where)
    modulus = material["elastic_modulus_gpa"] * 1000
    worst = None
    for axis in axes:
        force, component = forces[_SPINDLE if axis == _SPINDLE else "across"]
        inertia = (
            section_inertia_mm4(beam["section"], axis) if "section" in beam else 0.0
        )
        for station in stations:
            try:
                deflection, span = _deflection(beam, station, force, modulus * inertia)
            except CheckError as error:
                raise CheckError(f"{where}: {error}") from error
            if not math.isfinite(deflection):
                raise CheckError(f"{where}: numerical range exceeded")
            if limits[axis] is None or deflection <= limits[axis][0]:
                continue
            if worst is None or deflection > worst[0]:
                worst = (deflection, axis, station, span, component, inertia)
    if worst is None:
        return
    deflection, axis, station, span, component, inertia = worst
    raise CheckError(
        f"{where}: estimated bending {deflection:.3g} mm along {axis} exceeds the "
        f"{limits[axis][1]} at station {station:.6g} mm, {span}; "
        f"{component}, I {inertia:.6g} mm^4, E {material['elastic_modulus_gpa']:g} "
        f"GPa ({name}); static estimate at the cut, not measured error"
    )


def _tools(plan: LoadedPlan) -> dict[str, dict]:
    """Plan tools by id, with any stated helix or axial ratio validated."""
    tools = {}
    for tool in plan.data.get("tools", []):
        where = f"tool {tool.get('id')!r}"
        if "axial_ratio" in tool:
            _positive(tool["axial_ratio"], f"{where}.axial_ratio")
        if (
            "helix_deg" in tool
            and _positive(tool["helix_deg"], f"{where}.helix_deg") >= 90
        ):
            raise CheckError(f"{where}.helix_deg: expected an angle below 90°")
        tools[tool.get("id")] = tool
    return tools


def check(plan: LoadedPlan, config: dict) -> None:
    """Refuse missing coverage or excessive bending; emit nothing on a pass."""
    material = plan.data.get("milling_material")
    if material is not None and material not in config["materials"]:
        raise CheckError(
            f"milling_material: {material!r} must select a configured material"
        )
    context = {
        "config": config,
        "material": material,
        "tools": _tools(plan),
        # Every cut in plan order: a rough cut's finish_cut must come later.
        "cuts": [
            cut
            for setup in plan.data["setups"]
            for operation in setup["operations"]
            if isinstance(operation.get("milling_cuts"), list)
            for cut in operation["milling_cuts"]
        ],
    }
    operation_number = 0
    for index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {index} ({setup.get('title', 'untitled')})"
        machine = setup.get("machine_kind")
        if machine not in ("lathe", "other"):
            raise CheckError(f"{where}: machine_kind must declare lathe or other")
        numbered = []
        for operation in setup["operations"]:
            operation_number += 10
            numbered.append((f"{where}, Op {operation_number}", operation))
        if machine == "lathe":
            if "beam" in setup or any(
                "milling_cuts" in op or "beam" in op for _, op in numbered
            ):
                raise CheckError(
                    f"{where}: lathe setups take no beam or milling_cuts "
                    "(turning_deflection covers them)"
                )
            continue
        if "beam" not in setup:
            raise CheckError(f'{where}: missing beam (a table, or "other")')
        holds = []
        if setup.get("vise_hold", "other") != "other":
            holds = vise.holds(plan.shop_data, setup, where)
        setup_beam = setup["beam"]
        if setup_beam != "other":
            setup_beam = _beam(setup_beam, f"{where}.beam")
            _vise_link(setup_beam, holds, True, f"{where}.beam")
        for op_where, operation in numbered:
            speed = operation.get("speed_kind")
            if "tool" in operation and speed not in ("spindle", "other"):
                raise CheckError(
                    f"{op_where}: speed_kind must declare spindle or other"
                )
            cuts = operation.get("milling_cuts")
            if speed != "spindle":
                if cuts is not None or "beam" in operation:
                    raise CheckError(
                        f"{op_where}: only spindle operations take milling_cuts or beam"
                    )
                continue
            if cuts is None:
                raise CheckError(
                    f'{op_where}: missing milling_cuts (cut tables, or "other" '
                    "when the spindle removes no material)"
                )
            if cuts == "other":
                if "beam" in operation:
                    raise CheckError(f'{op_where}: milling_cuts "other" takes no beam')
                continue
            if not isinstance(cuts, list) or not cuts:
                raise CheckError(
                    f'{op_where}.milling_cuts: expected cut tables or "other"'
                )
            if setup_beam == "other":
                raise CheckError(
                    f'{where}: beam "other" is only for setups that cut nothing '
                    f"with the spindle; {op_where} declares milling_cuts"
                )
            beam = setup_beam
            if "beam" in operation:
                beam = _beam(operation["beam"], f"{op_where}.beam")
                _vise_link(beam, holds, False, f"{op_where}.beam")
            for cut_index, cut in enumerate(cuts, 1):
                if not isinstance(cut, dict):
                    raise CheckError(f"{op_where}, cut {cut_index}: expected a table")
                name = cut.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise CheckError(f"{op_where}, cut {cut_index}: missing name")
                try:
                    _check_cut(
                        cut, beam, operation, context, f"{op_where}, cut {name!r}"
                    )
                except TurningError as error:
                    raise CheckError(f"{op_where}, cut {name!r}: {error}") from error
                except ArithmeticError as error:
                    raise CheckError(
                        f"{op_where}, cut {name!r}: numerical range exceeded ({error})"
                    ) from error
