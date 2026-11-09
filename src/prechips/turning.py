"""Static workpiece bending screen for explicitly declared longitudinal cuts.

This is total transverse displacement at the moving tool, not actual diameter
error. All empirical coefficients and authored numerical assumptions live in
turning.toml. Ideal supports and a solid uniform minimum section omit machine
compliance, dynamics, heat and axial-force effects; this is not certification.
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
_DISABLE = "Explicit opt-out: --disable-check turning_deflection."
_MATERIAL_KEYS = {"unit_power_hp_min_per_in3", "elastic_modulus_gpa"}


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


def _load_config(path: Path | None) -> dict:
    config = _read_config(DEFAULT_CONFIG)
    if path is not None:
        overrides = _read_config(path)
        _keys(overrides, {"limits", "force", "materials"}, "turning config")
        for section, values in overrides.items():
            values = _table(values, f"turning config.{section}")
            if section == "materials":
                for name, material in values.items():
                    material = _table(material, f"materials.{name}")
                    config[section].setdefault(name, {}).update(material)
            else:
                config[section].update(values)
    _keys(config, {"limits", "force", "materials"}, "turning config")
    for section, keys in (
        ("limits", {"rough_mm", "finish_mm"}),
        ("force", {"radial_ratio", "rough_wear", "finish_wear", "feed_factors"}),
    ):
        table = _table(config.get(section), section)
        _keys(table, keys, section)
        for key in keys - {"feed_factors", "radial_ratio"}:
            table[key] = _positive(table.get(key), f"{section}.{key}")
    force = config["force"]
    force["radial_ratio"] = _number(
        force.get("radial_ratio"), "force.radial_ratio", minimum=0
    )
    pairs = force.get("feed_factors")
    if not isinstance(pairs, list) or len(pairs) < 2:
        raise TurningError(
            "force.feed_factors: expected at least two [feed, factor] pairs"
        )
    previous = 0.0
    for index, pair in enumerate(pairs):
        where = f"force.feed_factors[{index + 1}]"
        if not isinstance(pair, list) or len(pair) != 2:
            raise TurningError(f"{where}: expected [feed in/rev, factor]")
        feed, factor = (_positive(value, where) for value in pair)
        if feed <= previous:
            raise TurningError(f"{where}: feeds must be strictly ascending")
        previous = feed
        pairs[index] = [feed, factor]
    materials = _table(config.get("materials"), "materials")
    if not materials:
        raise TurningError("materials: expected at least one material")
    for name, material in materials.items():
        if not name.strip():
            raise TurningError("materials: material names must be nonempty")
        material = _table(material, f"materials.{name}")
        _keys(material, _MATERIAL_KEYS, f"materials.{name}")
        for key in _MATERIAL_KEYS:
            material[key] = _positive(material.get(key), f"materials.{name}.{key}")
    return config


def _feed_factor(feed_in_rev: float, pairs: list[list[float]]) -> float:
    if not pairs[0][0] <= feed_in_rev <= pairs[-1][0]:
        raise TurningError(
            f"feed {feed_in_rev:g} in/rev outside configured feed-factor table "
            f"[{pairs[0][0]:g}, {pairs[-1][0]:g}]; no extrapolation"
        )
    for (low, low_factor), (high, high_factor) in pairwise(pairs):
        if feed_in_rev <= high:
            return low_factor + (high_factor - low_factor) * (
                (feed_in_rev - low) / (high - low)
            )
    raise TurningError("feed-factor interpolation has no matching interval")


def _bounding_passes(start: float, end: float, doc: float) -> list[tuple[float, float]]:
    """Return (radial DOC, resulting diameter) for at most two actual passes.

    Equal full-depth passes have increasing compliance as diameter decreases:
    the last one bounds all earlier ones. The final partial-depth pass has a
    different force, so must be checked separately, never combined with full DOC.
    fmod avoids an unbounded pass loop or overflow-prone total/doc pass count.
    """
    total = (start - end) / 2
    if not math.isfinite(total) or not total > 0:
        raise TurningError(
            "start_diameter_mm must exceed end_diameter_mm by a finite amount"
        )
    remainder = math.fmod(total, doc)
    passes = []
    if total >= doc:
        passes.append((doc, end + 2 * remainder))
    if remainder > 0:
        passes.append((remainder, end))
    return passes


def _pinned_factor(start: float, end: float, span: float) -> tuple[float, float]:
    """Max delta*EI/F and tool distance for a pinned span, not free-end sag."""
    low, high = sorted((start, end))
    x = min(max(span / 2, low), high)
    return x**2 * (span - x) ** 2 / (3 * span), x


def _follower_factor(x: float, offset: float) -> float:
    """Load-point delta*EI/F with chuck and engaged follower point supports."""
    return x**2 * offset**2 / (3 * (x + offset))


def _bending_factor(
    support: dict, start: float, end: float
) -> tuple[float, float, str]:
    """Return maximum delta*EI/F, authored Z and support state at that tool Z."""
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
    if kind == "chuck_only":
        a, b = start - chuck, end - chuck
        if min(a, b) < 0 < max(a, b):
            raise TurningError(
                "cut crosses chuck support; declare only exposed cut stock"
            )
        z = max((start, end), key=lambda value: abs(value - chuck))
        return abs(z - chuck) ** 3 / 3, z, "chuck only"
    centre = _number(support.get("centre_z_mm"), "turning_support.centre_z_mm")
    span = abs(centre - chuck)
    if span == 0:
        raise TurningError("centre_z_mm must differ from chuck_z_mm")
    direction = 1 if centre > chuck else -1
    a, b = (start - chuck) * direction, (end - chuck) * direction
    if not 0 <= min(a, b) <= max(a, b) <= span:
        raise TurningError("cut must lie within the chuck-to-centre span")
    if kind == "tailstock":
        factor, x = _pinned_factor(a, b, span)
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
    before, before_x = _pinned_factor(a, e, span)
    # After engagement, chuck and follower are pinned supports with span x+s.
    # x^2*s^2/(3*(x+s)) increases with x >= 0: maximum at engagement.
    after = _follower_factor(e, offset)
    if before >= after:
        return before, chuck + direction * before_x, "before follower engagement"
    return after, engage, "follower engaged"


def _check_cut(cut: dict, support: dict, material: dict, config: dict) -> None:
    _keys(
        cut,
        {
            "name",
            "phase",
            "start_z_mm",
            "end_z_mm",
            "start_diameter_mm",
            "end_diameter_mm",
            "max_radial_doc_mm",
            "feed_mm_rev",
            "minimum_diameter_mm",
            "max_deflection_mm",
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
    }
    limit = _positive(
        cut.get("max_deflection_mm", config["limits"][f"{phase}_mm"]),
        "max_deflection_mm",
    )
    factor, worst_z, support_state = _bending_factor(support, start_z, end_z)
    feed = numbers["feed_mm_rev"] / 25.4
    force_config = config["force"]
    feed_factor = _feed_factor(feed, force_config["feed_factors"])
    force_per_doc = (
        396000
        * material["unit_power_hp_min_per_in3"]
        * feed_factor
        * force_config[f"{phase}_wear"]
        * feed
        / 25.4
        * 4.4482216152605
        * math.hypot(1, force_config["radial_ratio"])
    )
    modulus = material["elastic_modulus_gpa"] * 1000
    for doc, diameter in _bounding_passes(
        numbers["start_diameter_mm"],
        numbers["end_diameter_mm"],
        numbers["max_radial_doc_mm"],
    ):
        diameter = min(diameter, numbers["minimum_diameter_mm"])
        inertia = math.pi * diameter**4 / 64
        force = force_per_doc * doc
        rigidity = modulus * inertia
        if not math.isfinite(rigidity) or rigidity <= 0:
            raise TurningError("numerical range exceeded in bending stiffness")
        deflection = force * factor / rigidity
        if not all(math.isfinite(value) for value in (force, factor, deflection)):
            raise TurningError("numerical range exceeded in bending estimate")
        if deflection > limit:
            raise TurningError(
                f"estimated total transverse bending {deflection:.6g} mm exceeds "
                f"limit {limit:.6g} mm; transverse force {force:.6g} N, "
                f"worst Z {worst_z:.6g} mm ({support_state}), radial DOC {doc:.6g} mm, "
                f"model diameter {diameter:.6g} mm; not actual diameter error"
            )


def check_turning_deflection(plan: LoadedPlan, config_path: Path | None = None) -> None:
    """Refuse missing declared coverage or excessive bending; emit nothing on pass."""
    try:
        config = _load_config(config_path)
        operation_number = 0
        for setup_index, setup in enumerate(plan.data["setups"], 1):
            where = f"setup {setup_index} ({setup.get('title', 'untitled')})"
            machine = setup.get("machine_kind")
            if machine not in {"lathe", "other"}:
                raise TurningError(f"{where}: machine_kind must declare lathe or other")
            for operation in setup["operations"]:
                operation_number += 10
                if machine == "other":
                    continue
                op_where = f"{where}, Op {operation_number}"
                kind = operation.get("cut_kind")
                if kind not in {"longitudinal_turning", "other"}:
                    raise TurningError(
                        f"{op_where}: cut_kind must declare longitudinal_turning or other"
                    )
                if kind == "other":
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
                for cut_index, cut in enumerate(cuts, 1):
                    cut = _table(cut, f"{op_where}, cut {cut_index}")
                    cut_name = cut.get("name")
                    if not isinstance(cut_name, str) or not cut_name.strip():
                        raise TurningError(f"{op_where}, cut {cut_index}: missing name")
                    try:
                        _check_cut(cut, support, config["materials"][name], config)
                    except (TurningError, ArithmeticError) as error:
                        raise TurningError(
                            f"{op_where}, cut {cut_name!r}: {error}"
                        ) from error
    except TurningError as error:
        raise TurningError(f"turning_deflection: {error}. {_DISABLE}") from error
