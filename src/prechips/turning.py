"""Static workpiece bending screen for explicitly declared longitudinal cuts.

The compared quantity is radial displacement at the moving tool; the diameter
error it leaves is about twice that. The tangential component is reported but
moves the work along the cutting direction, a second-order diameter effect. All
empirical coefficients and authored numerical assumptions live in turning.toml.
Ideal supports and a solid uniform minimum section omit machine compliance,
dynamics, heat and axial-force effects; this is not certification. An
operation's ``turning_step`` replaces the uniform section with a stepped
cantilever for diameters turned in steps toward the chuck.
"""

from __future__ import annotations

import math
import tomllib
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

DEFAULT_CONFIG = Path(__file__).with_name("turning.toml")
INCH_MM = 25.4
LBF_N = 4.4482216152605
_DISABLE = "Explicit opt-out: --disable-check turning_deflection."
_MATERIAL_KEYS = {"unit_power_hp_min_per_in3", "elastic_modulus_gpa"}
# Only drilling and plunging read a material's handbook thrust factor.
_OPTIONAL_MATERIAL_KEYS = {"drill_kd"}
_SECTIONS = {
    "limits": {"rough_mm", "finish_mm"},
    "force": {"radial_ratio", "rough_wear", "finish_wear", "feed_factors"},
    "milling": {
        "rough_mm",
        "finish_mm",
        "radial_ratio",
        "axial_ratio",
        "wear",
        "face_wear",
    },
    "drilling": {
        "wear",
        "chisel_thrust_b",
        "chisel_thrust_j",
        "feed_factors",
        "diameter_factors",
    },
    "pecking": {
        "chip_break_above_ld",
        "full_retract_above_ld",
        "max_ld",
        "step_max_diameters",
    },
}
_FACTOR_TABLES = {"feed_factors", "diameter_factors"}


class TurningError(ValueError):
    """Missing coverage, invalid assumptions, or excessive estimated bending."""


def _table(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise TurningError(f"{where}: expected a table")
    return value


def _keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = table.keys() - allowed
    if unknown:
        raise TurningError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")


def _number(value: object, where: str, *, minimum: float | None = None) -> float:
    if type(value) not in (int, float):
        raise TurningError(f"{where}: expected a finite number")
    try:
        number = float(value)
    except OverflowError as error:
        raise TurningError(f"{where}: expected a finite number") from error
    if not math.isfinite(number):
        raise TurningError(f"{where}: expected a finite number")
    if minimum is not None and number < minimum:
        raise TurningError(f"{where}: must be >= {minimum:g}")
    return number


def _positive(value: object, where: str) -> float:
    number = _number(value, where)
    if number <= 0:
        raise TurningError(f"{where}: expected a positive number")
    return number


def _read_config(path: Path) -> dict:
    try:
        with path.open("rb") as source:
            return tomllib.load(source)
    except (OSError, ValueError) as error:
        raise TurningError(f"turning config {path}: {error}") from error


def _factor_pairs(pairs: object, where: str) -> list[list[float]]:
    if not isinstance(pairs, list) or len(pairs) < 2:
        raise TurningError(f"{where}: expected at least two [value, factor] pairs")
    previous = 0.0
    result = []
    for index, pair in enumerate(pairs):
        pair_where = f"{where}[{index + 1}]"
        if not isinstance(pair, list) or len(pair) != 2:
            raise TurningError(f"{pair_where}: expected [value, factor]")
        value, factor = (_positive(item, pair_where) for item in pair)
        if value <= previous:
            raise TurningError(f"{pair_where}: values must be strictly ascending")
        previous = value
        result.append([value, factor])
    return result


def load_config(path: Path | None) -> dict:
    """Packaged turning, milling, drilling and pecking data with a partial override."""
    config = _read_config(DEFAULT_CONFIG)
    if path is not None:
        overrides = _read_config(path)
        _keys(overrides, {*_SECTIONS, "materials"}, "turning config")
        for section, values in overrides.items():
            values = _table(values, f"turning config.{section}")
            if section == "materials":
                for name, material in values.items():
                    material = _table(material, f"materials.{name}")
                    config[section].setdefault(name, {}).update(material)
            else:
                config[section].update(values)
    _keys(config, {*_SECTIONS, "materials"}, "turning config")
    for section, keys in _SECTIONS.items():
        table = _table(config.get(section), section)
        _keys(table, keys, section)
        for key in keys - _FACTOR_TABLES:
            table[key] = _positive(table.get(key), f"{section}.{key}")
        for key in keys & _FACTOR_TABLES:
            table[key] = _factor_pairs(table.get(key), f"{section}.{key}")
    materials = _table(config.get("materials"), "materials")
    if not materials:
        raise TurningError("materials: expected at least one material")
    for name, material in materials.items():
        if not name.strip():
            raise TurningError("materials: material names must be nonempty")
        material = _table(material, f"materials.{name}")
        _keys(
            material,
            _MATERIAL_KEYS | _OPTIONAL_MATERIAL_KEYS,
            f"materials.{name}",
        )
        for key in _MATERIAL_KEYS | (_OPTIONAL_MATERIAL_KEYS & material.keys()):
            material[key] = _positive(material.get(key), f"materials.{name}.{key}")
    return config


def table_factor(
    value: float, pairs: list[list[float]], quantity: str, unit: str, table: str
) -> float:
    """Linear interpolation in an ascending [value, factor] table; no extrapolation."""
    if not pairs[0][0] <= value <= pairs[-1][0]:
        raise TurningError(
            f"{quantity} {value:g} {unit} outside configured {table} table "
            f"[{pairs[0][0]:g}, {pairs[-1][0]:g}]; no extrapolation"
        )
    for (low, low_factor), (high, high_factor) in pairwise(pairs):
        if value <= high:
            return low_factor + (high_factor - low_factor) * (
                (value - low) / (high - low)
            )
    raise TurningError(f"{table} interpolation has no matching interval")


def cutting_force_n(
    unit_power: float, feed_factor: float, wear: float, chip_area_in2: float
) -> float:
    """Handbook mean cutting force in newtons: unit power × removal rate ÷ speed.

    Pc = Kp*C*Q*W hp and Fc = 33000*Pc/V lbf; with Q = 12*V*A in^3/min for the
    mean uncut chip area A (in^2) this is Fc = 396000*Kp*C*W*A lbf.
    """
    return 396000 * unit_power * feed_factor * wear * chip_area_in2 * LBF_N


def _pinned_factor(start: float, end: float, span: float) -> tuple[float, float]:
    """Max delta*EI/F and tool distance for a pinned span, not free-end sag."""
    low, high = sorted((start, end))
    x = min(max(span / 2, low), high)
    return x**2 * (span - x) ** 2 / (3 * span), x


def _follower_factor(x: float, offset: float) -> float:
    """Load-point delta*EI/F with chuck and engaged follower point supports."""
    return x**2 * offset**2 / (3 * (x + offset))


def _bending_factor(
    support: dict, start: float, end: float, kept: tuple[float, float]
) -> tuple[float, float, str]:
    """Return maximum delta*EI/F, authored Z and support state at that tool Z.

    The whole traverse is validated against the supports; the maximum is taken
    over ``kept``, the authored Z pair of the retained feature inside it.
    """
    kind = support.get("kind")
    keys = {"kind", "chuck_z_mm"}
    if kind in {"tailstock", "follower"}:
        keys.add("centre_z_mm")
    if kind == "follower":
        keys.update({"engage_z_mm", "offset_mm", "pad_width_mm"})
    if kind not in {"chuck_only", "tailstock", "follower"}:
        raise TurningError(
            "turning_support.kind: expected chuck_only, tailstock or follower"
        )
    _keys(support, keys, "turning_support")
    chuck = _number(support.get("chuck_z_mm"), "turning_support.chuck_z_mm")
    if start == end:
        raise TurningError("start_z_mm and end_z_mm must describe a nonzero traverse")
    c_start, c_end = kept
    if (
        not min(start, end)
        <= min(c_start, c_end)
        <= max(c_start, c_end)
        <= max(start, end)
    ):
        raise TurningError("kept range must lie within the declared traverse")
    if kind == "chuck_only":
        a, b = start - chuck, end - chuck
        if min(a, b) < 0 < max(a, b):
            raise TurningError(
                "cut crosses chuck support; declare only exposed cut stock"
            )
        z = max((c_start, c_end), key=lambda value: abs(value - chuck))
        return abs(z - chuck) ** 3 / 3, z, "chuck only"
    centre = _number(support.get("centre_z_mm"), "turning_support.centre_z_mm")
    span = abs(centre - chuck)
    if span == 0:
        raise TurningError("centre_z_mm must differ from chuck_z_mm")
    direction = 1 if centre > chuck else -1
    a, b = (start - chuck) * direction, (end - chuck) * direction
    if not 0 <= min(a, b) <= max(a, b) <= span:
        raise TurningError("cut must lie within the chuck-to-centre span")
    c_low, c_high = sorted(((c_start - chuck) * direction, (c_end - chuck) * direction))
    if kind == "tailstock":
        factor, x = _pinned_factor(c_low, c_high, span)
        return factor, chuck + direction * x, "chuck and tailstock"
    engage = _number(support.get("engage_z_mm"), "turning_support.engage_z_mm")
    e = (engage - chuck) * direction
    offset = _positive(support.get("offset_mm"), "turning_support.offset_mm")
    width = _positive(support.get("pad_width_mm"), "turning_support.pad_width_mm")
    if not b <= e <= a or a <= b:
        raise TurningError(
            "follower requires toward-chuck traverse and engagement within cut"
        )
    if offset < width / 2 or e + offset + width / 2 > a:
        raise TurningError(
            "follower entire pad band must fit on the already-turned land at engagement "
            "(offset >= half pad width, far pad edge <= cut start)"
        )
    # The pad band stays between cut end and cut start throughout the remaining
    # toward-chuck traverse. Credit no support on a merely asserted contact flag.
    # Before engagement the tool is at x >= e on chuck/centre supports; after it,
    # chuck and follower are pinned supports with span x+s, and
    # x^2*s^2/(3*(x+s)) increases with x >= 0, so that maximum is at the
    # engagement end of the kept range.
    candidates = []
    if c_high >= e:
        before, before_x = _pinned_factor(max(c_low, e), c_high, span)
        candidates.append(
            (before, chuck + direction * before_x, "before follower engagement")
        )
    if c_low <= e:
        x = min(c_high, e)
        candidates.append(
            (_follower_factor(x, offset), chuck + direction * x, "follower engaged")
        )
    return max(candidates, key=lambda candidate: candidate[0])


def _turning_step(value: object) -> dict:
    """An operation's step turning toward the chuck: step length, load section."""
    step = _table(value, "turning_step")
    _keys(step, {"length_mm", "load_diameter_mm"}, "turning_step")
    return {
        key: _positive(step.get(key), f"turning_step.{key}")
        for key in ("length_mm", "load_diameter_mm")
    }


def _stepped_bending(
    per_doc: float,
    x: float,
    ahead: float,
    load_diameter: float,
    end_diameter: float,
    doc: float,
    modulus: float,
) -> tuple[float, float]:
    """Worst radial bending and its pass depth, the tool ``x`` mm from the chuck.

    The finished length outboard of the tool carries no load. Between the
    tool and the chuck lie ``ahead`` mm of the step being cut, which earlier
    passes of that step have turned: a pass ``t`` deep meets it at no less
    than end + 2t (exactly the start diameter for a single pass). The rest,
    to the jaws, is the load section. Over every pass depth up to ``doc``,
    g(t) = t (A + B / (e + 2t)^4): its slope A + B (e - 6t) / (e + 2t)^5 is
    positive below e/6, falls to e/3 and rises towards A after, so the
    maximum is at ``doc`` or at the slope's first root.
    """
    chuck_side = (x**3 - ahead**3) / (3 * modulus * math.pi * load_diameter**4 / 64)
    step_side = 64 * ahead**3 / (3 * modulus * math.pi)

    def bend(t: float) -> float:
        return per_doc * t * (chuck_side + step_side / (end_diameter + 2 * t) ** 4)

    def slope(t: float) -> float:
        return (
            chuck_side
            + step_side * (end_diameter - 6 * t) / (end_diameter + 2 * t) ** 5
        )

    depths = [doc]
    low, high = end_diameter / 6, min(doc, end_diameter / 3)
    if high > low and slope(high) < 0:
        for _ in range(200):
            middle = (low + high) / 2
            if slope(middle) >= 0:
                low = middle
            else:
                high = middle
        depths += [low, high]
    return max((bend(t), t) for t in depths)


def _check_cut(
    cut: dict, support: dict, material: dict, config: dict, step: dict | None = None
) -> None:
    if step is not None and "minimum_diameter_mm" in cut:
        raise TurningError(
            "a step-turned cut takes no minimum_diameter_mm: "
            "turning_step.load_diameter_mm is the section between the holding "
            "and the step"
        )
    numeric = {
        "start_diameter_mm",
        "end_diameter_mm",
        "max_radial_doc_mm",
        "feed_mm_rev",
    }
    if step is None:
        numeric.add("minimum_diameter_mm")
    _keys(
        cut,
        {
            "name",
            "phase",
            "start_z_mm",
            "end_z_mm",
            *numeric,
            "max_deflection_mm",
            "kept_start_z_mm",
            "kept_end_z_mm",
        },
        "turning cut",
    )
    phase = cut.get("phase")
    if phase not in {"rough", "finish"}:
        raise TurningError("phase: expected rough or finish")
    start_z = _number(cut.get("start_z_mm"), "start_z_mm")
    end_z = _number(cut.get("end_z_mm"), "end_z_mm")
    numbers = {
        key: _positive(cut.get(key), key)
        for key in (
            "start_diameter_mm",
            "end_diameter_mm",
            "max_radial_doc_mm",
            "feed_mm_rev",
            "minimum_diameter_mm",
        )
        if key in numeric
    }
    phase_limit = config["limits"][f"{phase}_mm"]
    limit = min(
        phase_limit,
        _positive(cut.get("max_deflection_mm", phase_limit), "max_deflection_mm"),
    )
    # The author states which part of the traverse is retained; sacrificial
    # stubs, run-in and parted-off ends are traversed but not held to the limit.
    kept = (
        _number(cut.get("kept_start_z_mm"), "kept_start_z_mm"),
        _number(cut.get("kept_end_z_mm"), "kept_end_z_mm"),
    )
    factor, worst_z, support_state = _bending_factor(support, start_z, end_z, kept)
    traverse = _bending_factor(support, start_z, end_z, (start_z, end_z))
    feed = numbers["feed_mm_rev"] / INCH_MM
    force_config = config["force"]
    feed_factor = table_factor(
        feed, force_config["feed_factors"], "feed", "in/rev", "feed-factor"
    )
    # Handbook cutting (tangential) force per mm of radial DOC, in newtons.
    tangential_per_doc = cutting_force_n(
        material["unit_power_hp_min_per_in3"],
        feed_factor,
        force_config[f"{phase}_wear"],
        feed / INCH_MM,
    )
    modulus = material["elastic_modulus_gpa"] * 1000
    total_removal = (numbers["start_diameter_mm"] - numbers["end_diameter_mm"]) / 2
    if not math.isfinite(total_removal) or total_removal <= 0:
        raise TurningError(
            "start_diameter_mm must exceed end_diameter_mm by a finite amount"
        )
    # Maximum DOC does not specify pass order: a full-depth pass may be last.
    # Bound every permitted schedule at the final minimum diameter. Authors
    # can declare individual pass records when a tighter bound is needed.
    doc = min(numbers["max_radial_doc_mm"], total_removal)
    if step is not None:
        _check_stepped(
            step,
            support,
            (start_z, end_z),
            kept,
            worst_z,
            tangential_per_doc * force_config["radial_ratio"],
            tangential_per_doc,
            numbers["end_diameter_mm"],
            doc,
            modulus,
            limit,
        )
        return
    diameter = min(numbers["end_diameter_mm"], numbers["minimum_diameter_mm"])
    inertia = math.pi * diameter**4 / 64
    tangential = tangential_per_doc * doc
    force = tangential * force_config["radial_ratio"]
    rigidity = modulus * inertia
    if not math.isfinite(rigidity) or rigidity <= 0:
        raise TurningError("numerical range exceeded in bending stiffness")
    deflection = force * factor / rigidity
    traverse_deflection = force * traverse[0] / rigidity
    if not all(
        math.isfinite(value)
        for value in (force, factor, deflection, traverse_deflection)
    ):
        raise TurningError("numerical range exceeded in bending estimate")
    if deflection <= limit:
        return
    raise TurningError(
        f"estimated radial bending {deflection:.6g} mm (about {2 * deflection:.6g} mm "
        f"on diameter) exceeds limit {limit:.6g} mm at Z {worst_z:.6g} mm "
        f"({support_state}) over kept Z {kept[0]:.6g}..{kept[1]:.6g} mm; whole "
        f"traverse {traverse_deflection:.6g} mm at Z {traverse[1]:.6g} mm "
        f"({traverse[2]}); radial force {force:.6g} N, tangential {tangential:.6g} N, "
        f"radial DOC {doc:.6g} mm, model diameter {diameter:.6g} mm; static "
        "estimate, not measured diameter error"
    )


def _check_stepped(
    step: dict,
    support: dict,
    traverse: tuple[float, float],
    kept: tuple[float, float],
    worst_z: float,
    radial_per_doc: float,
    tangential_per_doc: float,
    end_diameter: float,
    doc: float,
    modulus: float,
    limit: float,
) -> None:
    """Bend a cut turned in steps toward the chuck, each step finished first.

    Bending only grows as the tool moves out, so the worst step is the one at
    the farthest kept Z; within it, the step ahead of the tool is as long as
    it can be there, no longer than the declared step nor than the traverse
    left toward the chuck.
    """
    chuck = support["chuck_z_mm"]
    start_z, end_z = traverse
    near, far = abs(end_z - chuck), abs(start_z - chuck)
    if far <= near:
        raise TurningError(
            "turning_step: the traverse must run toward the chuck (start_z_mm "
            "farther from it than end_z_mm), the finished length outboard of the tool"
        )
    length = step["length_mm"]
    if length > far - near:
        raise TurningError(
            f"turning_step.length_mm {length:.6g} mm exceeds the "
            f"{far - near:.6g} mm traverse"
        )
    load = step["load_diameter_mm"]
    results = []
    for x in (abs(worst_z - chuck), far):
        ahead = min(length, x - near)
        bending, depth = _stepped_bending(
            radial_per_doc, x, ahead, load, end_diameter, doc, modulus
        )
        if not math.isfinite(bending):
            raise TurningError("numerical range exceeded in bending estimate")
        results.append((bending, depth, ahead))
    (deflection, depth, ahead), (whole, _, _) = results
    if deflection <= limit:
        return
    force = radial_per_doc * depth
    raise TurningError(
        f"estimated radial bending {deflection:.6g} mm (about {2 * deflection:.6g} mm "
        f"on diameter) exceeds limit {limit:.6g} mm at Z {worst_z:.6g} mm "
        f"(chuck only, steps of {length:.6g} mm toward the chuck) over kept Z "
        f"{kept[0]:.6g}..{kept[1]:.6g} mm; whole traverse {whole:.6g} mm at Z "
        f"{start_z:.6g} mm; radial force {force:.6g} N, tangential "
        f"{tangential_per_doc * depth:.6g} N, radial DOC {depth:.6g} mm, load "
        f"section Ø{load:.6g} mm, {ahead:.6g} mm of step ahead of the tool at "
        f"Ø{end_diameter + 2 * depth:.6g} mm or more; static estimate, not "
        "measured diameter error"
    )


def check_turning_deflection(plan: LoadedPlan, config: dict) -> None:
    """Refuse missing declared coverage or excessive bending; emit nothing on pass.

    ``config`` is :func:`load_config`'s result, parsed once per render.
    """
    try:
        operation_number = 0
        for setup_index, setup in enumerate(plan.data["setups"], 1):
            where = f"setup {setup_index} ({setup.get('title', 'untitled')})"
            machine = setup.get("machine_kind")
            if machine not in {"lathe", "other"}:
                raise TurningError(f"{where}: machine_kind must declare lathe or other")
            if machine == "other" and "turning_support" in setup:
                raise TurningError(
                    f"{where}: machine_kind other contradicts turning_support"
                )
            for operation in setup["operations"]:
                operation_number += 10
                op_where = f"{where}, Op {operation_number}"
                kind = operation.get("cut_kind")
                if machine == "other":
                    if (
                        kind == "longitudinal_turning"
                        or "turning_cuts" in operation
                        or "turning_step" in operation
                    ):
                        raise TurningError(
                            f"{op_where}: machine_kind other contradicts "
                            "longitudinal turning data"
                        )
                    continue
                if kind not in {"longitudinal_turning", "other"}:
                    raise TurningError(
                        f"{op_where}: cut_kind must declare longitudinal_turning or other"
                    )
                if kind == "other":
                    for key in ("turning_cuts", "turning_step"):
                        if key in operation:
                            raise TurningError(
                                f"{op_where}: cut_kind other contradicts {key}"
                            )
                    continue
                cuts = operation.get("turning_cuts")
                if not isinstance(cuts, list) or not cuts:
                    raise TurningError(
                        f"{op_where}: missing nonempty turning_cuts coverage"
                    )
                support = _table(
                    setup.get("turning_support"), f"{op_where}.turning_support"
                )
                name = plan.data.get("turning_material")
                if not isinstance(name, str) or name not in config["materials"]:
                    raise TurningError(
                        f"{op_where}: turning_material {name!r} must select a "
                        "configured material"
                    )
                step = None
                if "turning_step" in operation:
                    try:
                        step = _turning_step(operation["turning_step"])
                    except TurningError as error:
                        raise TurningError(f"{op_where}.{error}") from error
                    if support.get("kind") != "chuck_only":
                        raise TurningError(
                            f"{op_where}.turning_step: step turning toward the "
                            "chuck needs chuck_only support; a tailstock or "
                            "follower would load the finished length outboard of "
                            "the tool"
                        )
                for cut_index, cut in enumerate(cuts, 1):
                    cut = _table(cut, f"{op_where}, cut {cut_index}")
                    cut_name = cut.get("name")
                    if not isinstance(cut_name, str) or not cut_name.strip():
                        raise TurningError(f"{op_where}, cut {cut_index}: missing name")
                    try:
                        _check_cut(
                            cut, support, config["materials"][name], config, step
                        )
                    except (TurningError, ArithmeticError) as error:
                        raise TurningError(
                            f"{op_where}, cut {cut_name!r}: {error}"
                        ) from error
                if step is not None:
                    stock = max(cut["start_diameter_mm"] for cut in cuts)
                    if step["load_diameter_mm"] > stock:
                        raise TurningError(
                            f"{op_where}.turning_step.load_diameter_mm: "
                            f"Ø{step['load_diameter_mm']:.6g} mm is over the "
                            f"Ø{stock:.6g} mm the operation starts from"
                        )
    except TurningError as error:
        raise TurningError(f"turning_deflection: {error}. {_DISABLE}") from error
