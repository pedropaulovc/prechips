"""Shared shop records read by declared-input checks.

Values are used as authored: the shop file is the source for machine, workholding
and gauge facts, and only records a plan actually references are validated.
"""

from itertools import pairwise
from math import isfinite

from prechips.checks import CheckError


def _positive(value: object, where: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise CheckError(f"{where}: expected a positive number")
    return float(value)


def _count(value: object, where: str) -> int:
    if type(value) is not int or value < 1:
        raise CheckError(f"{where}: expected a positive integer")
    return value


def _pair(value: object, where: str) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise CheckError(f"{where}: expected [low, high]")
    low, high = (float(item) if type(item) in (int, float) else None for item in value)
    if low is None or high is None or not isfinite(low) or not isfinite(high):
        raise CheckError(f"{where}: expected two finite numbers")
    if low < 0 or low > high:
        raise CheckError(f"{where}: expected 0 <= low <= high")
    return low, high


def _ranges(value: object, where: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or not value:
        raise CheckError(f"{where}: expected a nonempty array of [low, high]")
    ranges = [_pair(item, f"{where}[{index}]") for index, item in enumerate(value, 1)]
    if any(later[0] < earlier[1] for earlier, later in pairwise(ranges)):
        raise CheckError(f"{where}: expected ascending ranges")
    return ranges


def _sizes(value: object, where: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise CheckError(f"{where}: expected a nonempty array of sizes")
    return [_positive(item, f"{where}[{index}]") for index, item in enumerate(value, 1)]


def _axes(value: object, where: str) -> dict[str, float]:
    if not isinstance(value, dict) or value.keys() != {"x", "y", "z"}:
        raise CheckError(f"{where}: expected x, y and z")
    return {axis: _positive(item, f"{where}.{axis}") for axis, item in value.items()}


def _plates(value: object, where: str) -> dict[str, list[int]]:
    if not isinstance(value, dict) or not value:
        raise CheckError(f"{where}: expected named hole-circle lists")
    plates = {}
    for name, circles in value.items():
        if not isinstance(circles, list) or not circles:
            raise CheckError(f"{where}.{name}: expected a nonempty array of counts")
        plates[name] = [
            _count(item, f"{where}.{name}[{index}]")
            for index, item in enumerate(circles, 1)
        ]
    return plates


def _choice(*choices: str):
    def validate(value: object, where: str) -> str:
        if value not in choices:
            raise CheckError(f"{where}: expected {' or '.join(choices)}")
        return value

    return validate


_RECORDS = {
    "machines": {
        "kind": _choice("mill", "lathe", "dividing_head"),
        "rpm_ranges": _ranges,
        "travel_mm": _axes,
        "spindle_to_table_mm": _pair,
        "swing_over_bed_mm": _positive,
        "swing_over_cross_slide_mm": _positive,
        "between_centres_mm": _positive,
        "worm_ratio": _count,
        "plate_holes": _plates,
        "direct_index_positions": _count,
    },
    "workholding": {
        "kind": _choice("chuck", "collet", "vise"),
        "grip_range_mm": _pair,
        "grip_sizes_mm": _sizes,
        "body_diameter_mm": _positive,
        "body_length_mm": _positive,
        "jaw_width_mm": _positive,
        "jaw_height_mm": _positive,
        "opening_mm": _positive,
        "bed_height_mm": _positive,
    },
    "gauges": {
        "range_mm": _pair,
        "resolution_mm": _positive,
    },
}
_LIMITS = {
    "stickout_ld_max": _positive,
    "tool_change_clearance_mm": _positive,
    "vise_grip_min_mm": _positive,
    "vise_stickup_ratio_max": _positive,
    "vise_overhang_ratio_max": _positive,
}


def record(shop: dict, section: str, key: object, where: str) -> dict:
    """Return one referenced record with every authored field validated."""
    records = shop.get(section, {})
    if not isinstance(records, dict):
        raise CheckError(f"shop.{section}: expected a table")
    if not isinstance(key, str) or key not in records:
        raise CheckError(f"{where}: unknown shop {section} reference {key!r}")
    source = records[key]
    name = f"shop.{section}.{key}"
    if not isinstance(source, dict):
        raise CheckError(f"{name}: expected a table")
    unknown = source.keys() - _RECORDS[section].keys()
    if unknown:
        raise CheckError(f"{name}: unknown field(s): {', '.join(sorted(unknown))}")
    result = {
        field: _RECORDS[section][field](value, f"{name}.{field}")
        for field, value in source.items()
    }
    result["where"] = name
    return result


def fact(record_: dict, field: str):
    """Return a field a check depends on; missing data is never assumed."""
    if field not in record_:
        raise CheckError(f"{record_['where']}.{field}: required but not declared")
    return record_[field]


def limit(shop: dict, key: str) -> float:
    """Return one shop-wide limit from ``[limits]``."""
    limits = shop.get("limits", {})
    if not isinstance(limits, dict):
        raise CheckError("shop.limits: expected a table")
    unknown = limits.keys() - _LIMITS.keys()
    if unknown:
        raise CheckError(f"shop.limits: unknown field(s): {', '.join(sorted(unknown))}")
    if key not in limits:
        raise CheckError(f"shop.limits.{key}: required but not declared")
    return _LIMITS[key](limits[key], f"shop.limits.{key}")
