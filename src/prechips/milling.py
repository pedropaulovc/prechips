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
from pathlib import Path
from typing import TYPE_CHECKING

from prechips.checks import CheckError
from prechips.turning import TurningError, load_config, table_factor

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

INCH = 25.4
LBF_N = 4.4482216152605
_AXES = ("x", "y", "z")
_SPINDLE = "z"
_MILLING = ("side", "end", "face", "slot")
_THRUST = ("plunge", "drill")
_HOLDS = {
    "cantilever": {"clamp_mm", "section_mm"},
    "between": {"supports_mm", "section_mm"},
    "solid": {"seat", "seat_mm"},
}
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
    "bending",
    "max_deflection_mm",
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

    Pc = Kp*C*Q*W hp with Q = ft*nt*N*w*d in^3/min, V = pi*D*N/12 ft/min, and
    Ft = 33000*Pc/V = 396000*Kp*C*W*w*d*ft*nt/(pi*D) lbf; rpm cancels.
    """
    removal_per_rev = (
        (woc_mm / INCH) * (doc_mm / INCH) * (feed_per_tooth_mm / INCH) * flutes
    )
    lbf = (
        396000
        * unit_power
        * feed_factor
        * wear
        * removal_per_rev
        / (math.pi * cutter_dia_mm / INCH)
    )
    return lbf * LBF_N


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
    diameter = dia_mm / INCH
    lips = 2 * kd * feed_factor * diameter_factor * chisel_b * wear
    chisel = kd * diameter**2 * chisel_j * wear
    return (lips + chisel) * LBF_N


def _number(value: object, where: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise CheckError(f"{where}: expected a finite number")
    return float(value)


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
    if hold not in _HOLDS:
        raise CheckError(f"{where}.hold: expected cantilever, between or solid")
    keys = {"axis", "hold", "extent_mm"} | _HOLDS[hold]
    _fields(value, keys, keys, where)
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
    return beam


def _bending(value: object, beam: dict, kind: str, where: str) -> list[str]:
    axes = [value] if isinstance(value, str) else value
    if (
        not isinstance(axes, list)
        or not axes
        or any(axis not in _AXES for axis in axes)
        or len(set(axes)) != len(axes)
    ):
        raise CheckError(f"{where}: expected x, y or z, or an array of them")
    if beam["axis"] in axes:
        raise CheckError(
            f"{where}: {beam['axis']} is along the beam; bending is across it"
        )
    if kind in _THRUST and axes != [_SPINDLE]:
        raise CheckError(f"{where}: {kind} cuts load the beam along the spindle (z)")
    return axes


def _feed_per_tooth(cut: dict, flutes: int, where: str) -> float:
    if "feed_per_tooth_mm" in cut:
        if {"rpm", "feed_mm_min"} & cut.keys():
            raise CheckError(
                f"{where}: declare feed_per_tooth_mm or rpm with feed_mm_min, not both"
            )
        return _positive(cut["feed_per_tooth_mm"], f"{where}.feed_per_tooth_mm")
    if not {"rpm", "feed_mm_min"} <= cut.keys():
        raise CheckError(f"{where}: missing feed_per_tooth_mm or rpm with feed_mm_min")
    rpm = _positive(cut["rpm"], f"{where}.rpm")
    return _positive(cut["feed_mm_min"], f"{where}.feed_mm_min") / (rpm * flutes)


def _forces(cut: dict, kind: str, material: dict, config: dict, where: str) -> dict:
    """Force (N) and its description for each bending direction class."""
    diameter = _positive(cut["cutter_dia_mm"], f"{where}.cutter_dia_mm")
    flutes = cut["flutes"]
    if type(flutes) is not int or flutes < 1:
        raise CheckError(f"{where}.flutes: expected a positive integer")
    feed = _feed_per_tooth(cut, flutes, where)
    if kind in _THRUST:
        if {"axial_doc_mm", "radial_woc_mm"} & cut.keys():
            raise CheckError(
                f"{where}: {kind} thrust takes no axial_doc_mm or radial_woc_mm"
            )
        if "drill_kd" not in material:
            raise CheckError(f"{where}: material {cut['material']!r} has no drill_kd")
        drilling = config["drilling"]
        thrust = drill_thrust_n(
            material["drill_kd"],
            table_factor(
                feed * flutes / INCH,
                drilling["feed_factors"],
                "feed",
                "in/rev",
                "drilling feed-factor",
            ),
            table_factor(
                diameter / INCH,
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
            feed / INCH,
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
    along = tangential * milling["axial_ratio"]
    along_text = (
        f"axial force {along:.3g} N (tangential {tangential:.3g} N × "
        f"axial_ratio {milling['axial_ratio']:g})"
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


def _check_cut(cut: dict, beam: dict, config: dict, where: str) -> None:
    required = {
        "name",
        "kind",
        "phase",
        "material",
        "cutter_dia_mm",
        "flutes",
        "stations_mm",
        "bending",
    }
    _fields(cut, required, _CUT_KEYS, where)
    kind = cut["kind"]
    if kind not in _MILLING + _THRUST:
        raise CheckError(f"{where}.kind: expected {', '.join(_MILLING + _THRUST)}")
    phase = cut["phase"]
    if phase not in ("rough", "finish"):
        raise CheckError(f"{where}.phase: expected rough or finish")
    name = cut["material"]
    material = config["materials"].get(name) if isinstance(name, str) else None
    if material is None:
        raise CheckError(
            f"{where}.material: {name!r} must select a configured material"
        )
    axes = _bending(cut["bending"], beam, kind, f"{where}.bending")
    stations = cut["stations_mm"]
    stations = stations if isinstance(stations, list) else [stations]
    if not stations:
        raise CheckError(f"{where}.stations_mm: expected at least one station")
    stations = [_number(station, f"{where}.stations_mm") for station in stations]
    extent = beam["extent"]
    for station in stations:
        if not extent[0] <= station <= extent[1]:
            raise CheckError(
                f"{where}.stations_mm: {station:g} mm lies off the part "
                f"{extent[0]:g}..{extent[1]:g} mm"
            )
    limit = config["milling"][f"{phase}_mm"]
    if "max_deflection_mm" in cut:
        limit = min(
            limit, _positive(cut["max_deflection_mm"], f"{where}.max_deflection_mm")
        )
    forces = _forces(cut, kind, material, config, where)
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
            if worst is None or deflection > worst[0]:
                worst = (deflection, axis, station, span, component, inertia)
    deflection, axis, station, span, component, inertia = worst
    if deflection <= limit:
        return
    raise CheckError(
        f"{where}: estimated bending {deflection:.3g} mm along {axis} exceeds the "
        f"{phase} limit {limit:g} mm at station {station:.6g} mm, {span}; "
        f"{component}, I {inertia:.6g} mm^4, E {material['elastic_modulus_gpa']:g} "
        f"GPa ({cut['material']}); static estimate at the cut, not measured error"
    )


def check(plan: LoadedPlan, config_path: Path | None = None) -> None:
    """Refuse missing coverage or excessive bending; emit nothing on a pass."""
    try:
        config = load_config(config_path)
    except TurningError as error:
        raise CheckError(str(error)) from error
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
            if "beam" in setup or any("milling_cuts" in op for _, op in numbered):
                raise CheckError(
                    f"{where}: lathe setups take no beam or milling_cuts "
                    "(turning_deflection covers them)"
                )
            continue
        if "beam" not in setup:
            raise CheckError(f'{where}: missing beam (a table, or "other")')
        setup_beam = setup["beam"]
        if setup_beam != "other":
            setup_beam = _beam(setup_beam, f"{where}.beam")
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
            if "beam" in operation:
                beam = _beam(operation["beam"], f"{op_where}.beam")
            elif setup_beam == "other":
                raise CheckError(
                    f'{where}: beam "other" is only for setups that cut nothing '
                    f"with the spindle; {op_where} declares milling_cuts"
                )
            else:
                beam = setup_beam
            for cut_index, cut in enumerate(cuts, 1):
                if not isinstance(cut, dict):
                    raise CheckError(f"{op_where}, cut {cut_index}: expected a table")
                name = cut.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise CheckError(f"{op_where}, cut {cut_index}: missing name")
                try:
                    _check_cut(cut, beam, config, f"{op_where}, cut {name!r}")
                except TurningError as error:
                    raise CheckError(f"{op_where}, cut {name!r}: {error}") from error
