"""Calculated spindle speeds and feeds, and the ``cutting_speeds`` check.

Shared settings may declare surface speed instead of a literal rpm and a feed
per revolution or per tooth instead of literal feed text. The arithmetic
follows the archived speeds_feeds rule: rpm = 12*sfm/(pi*D_in), rounded to the
nearest 50 with ties to even, clamped to the machine's limits, and dropped to
the top of the range below when it falls in a gap between spindle ranges.
"""

from math import ceil, floor, isfinite, pi

from prechips import shop
from prechips.checks import CheckError

# Shared-setting fields beyond the literal ``rpm`` and ``feed``.
SETTING_FIELDS = frozenset(
    {"sfm", "feed_mm_rev", "chip_load_mm_per_tooth", "flutes", "feed_unit"}
)


def _positive(value: object, where: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise CheckError(f"{where}: expected a positive number")
    return float(value)


def calculated_rpm(raw_rpm: float, ranges: list[tuple[float, float]]) -> int:
    """Round to the nearest 50 (ties to even), then fit to ascending spindle ranges."""
    rpm = round(raw_rpm / 50) * 50
    rpm = max(ceil(ranges[0][0]), min(floor(ranges[-1][1]), rpm))
    if any(low <= rpm <= high for low, high in ranges):
        return rpm
    return floor(max(high for _, high in ranges if high < rpm))


def _ranges_text(ranges: list[tuple[float, float]]) -> str:
    return ", ".join(f"{low:g}–{high:g}" for low, high in ranges) + " rpm"


def setting_values(
    shared: dict,
    where: str,
    operation: dict,
    op_where: str,
    machine_ref: str | None,
    shop_data: dict,
) -> dict:
    """Return the rpm and feed text one shared setting supplies to an operation.

    Literal values pass through. ``sfm`` needs the operation's
    ``cut_diameter_mm`` and the setup's machine; per-tooth feeds use the
    operation's resolved rpm. Values the operation authors are not calculated.
    """
    if "rpm" in shared and "sfm" in shared:
        raise CheckError(f"{where}: declare rpm or sfm, not both")
    feeds = {"feed", "feed_mm_rev", "chip_load_mm_per_tooth"} & shared.keys()
    if len(feeds) > 1:
        raise CheckError(f"{where}: declare only one of {', '.join(sorted(feeds))}")
    chip_load = "chip_load_mm_per_tooth" in shared
    for key in ("flutes", "feed_unit"):
        if key in shared and not chip_load:
            raise CheckError(f"{where}.{key}: requires chip_load_mm_per_tooth")
    if chip_load:
        _positive(shared["chip_load_mm_per_tooth"], f"{where}.chip_load_mm_per_tooth")
        flutes = shared.get("flutes")
        if type(flutes) is not int or flutes < 1:
            raise CheckError(f"{where}.flutes: expected a positive integer")
        if shared.get("feed_unit", "mm/min") not in {"mm/min", "in/min"}:
            raise CheckError(f"{where}.feed_unit: expected mm/min or in/min")
    if "sfm" in shared:
        _positive(shared["sfm"], f"{where}.sfm")
    if "feed_mm_rev" in shared:
        _positive(shared["feed_mm_rev"], f"{where}.feed_mm_rev")

    values = {}
    rpm = operation.get("rpm", shared.get("rpm"))
    if "rpm" not in operation and "sfm" in shared:
        if "cut_diameter_mm" not in operation:
            raise CheckError(f"{op_where}.cut_diameter_mm: required by {where}.sfm")
        diameter = _positive(
            operation["cut_diameter_mm"], f"{op_where}.cut_diameter_mm"
        )
        if machine_ref is None:
            raise CheckError(f"{op_where}: {where}.sfm requires setup machine_ref")
        machine = shop.record(
            shop_data, "machines", machine_ref, f"{op_where}.machine_ref"
        )
        ranges = shop.fact(machine, "rpm_ranges")
        rpm = calculated_rpm(12 * shared["sfm"] / (pi * diameter / 25.4), ranges)
    if rpm is not None:
        values["rpm"] = rpm
    if "feed" in shared:
        values["feed"] = shared["feed"]
    if "feed_mm_rev" in shared:
        values["feed"] = f"{shared['feed_mm_rev']:g} mm/rev"
    if chip_load and "feed" not in operation:
        if rpm is None:
            raise CheckError(
                f"{op_where}: {where}.chip_load_mm_per_tooth requires an rpm or sfm"
            )
        feed = rpm * shared["flutes"] * shared["chip_load_mm_per_tooth"]
        values["feed"] = f"{round(feed)} mm/min"
        if shared.get("feed_unit") == "in/min":
            values["feed"] = f"{round(feed / 25.4, 1):g} in/min"
    return values


def check(plan) -> None:
    """Every tooled operation declares its speed kind; spindle speeds fit the machine."""
    operation_number = 0
    for setup_index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {setup_index} ({setup['title']})"
        for operation in setup["operations"]:
            operation_number += 10
            op_where = f"{where}, Op {operation_number}"
            kind = operation.get("speed_kind")
            rpm = operation.get("rpm")
            if "tool" not in operation:
                if kind is not None:
                    raise CheckError(f"{op_where}: speed_kind requires a tool")
                if rpm is not None:
                    raise CheckError(f"{op_where}: {rpm} rpm without a tool")
                continue
            if kind not in {"spindle", "other"}:
                raise CheckError(
                    f"{op_where}: speed_kind must declare spindle or other"
                )
            if kind == "other":
                if rpm is not None:
                    raise CheckError(
                        f"{op_where}: speed_kind other contradicts {rpm} rpm"
                    )
                continue
            if rpm is None:
                raise CheckError(f"{op_where}: spindle operation has no rpm")
            if "machine_ref" not in setup:
                raise CheckError(f"{op_where}: spindle operation requires machine_ref")
            machine = shop.record(
                plan.shop_data, "machines", setup["machine_ref"], f"{where}.machine_ref"
            )
            ranges = shop.fact(machine, "rpm_ranges")
            if not any(low <= rpm <= high for low, high in ranges):
                raise CheckError(
                    f"{op_where}: {rpm} rpm is outside {machine['where']} "
                    f"rpm_ranges {_ranges_text(ranges)}"
                )
