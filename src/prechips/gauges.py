"""Gauge capability: every declared inspection band fits its named gauge.

A setup or operation with ``inspection`` text declares ``gauge_checks``: either
``"other"`` (non-dimensional acceptance such as finish, fit-up or visual) or one
``{ gauge, band_mm }`` entry per dimensional limit the text states. The gauge's
``range_mm`` must contain both band ends and its ``resolution_mm`` must not exceed
the band width (high - low). An optional ``transfer`` names the transfer tool
(telescoping or small-hole gauge) set in the feature and read on ``gauge``: its
``range_mm`` must also contain both band ends. A transfer tool gives no reading
of its own, so the resolution rule stays with the reading gauge. An entry's
``requirements`` belong to ``requirement_coverage`` and are not read here.
"""

from __future__ import annotations

from math import isclose, isfinite
from typing import TYPE_CHECKING

from prechips import shop
from prechips.checks import CheckError

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_SHAPE = 'expected "other" or a nonempty array of { gauge, band_mm } tables'
_ENTRY = {"gauge", "band_mm", "transfer", "requirements"}


def band(value: object, where: str) -> tuple[float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(type(item) not in (int, float) or not isfinite(item) for item in value)
    ):
        raise CheckError(f"{where}: expected [low, high] as two finite numbers in mm")
    low, high = float(value[0]), float(value[1])
    if low > high:
        raise CheckError(f"{where}: expected low <= high")
    return low, high


def _within(gauge: dict, low: float, high: float, where: str) -> None:
    span_low, span_high = shop.fact(gauge, "range_mm")
    if low < span_low or high > span_high:
        raise CheckError(
            f"{where}: band {low:g}–{high:g} mm is outside {gauge['where']} "
            f"range {span_low:g}–{span_high:g} mm"
        )


def _capable(item: object, shop_data: dict, where: str) -> None:
    if (
        not isinstance(item, dict)
        or not {"gauge", "band_mm"} <= item.keys()
        or not item.keys() <= _ENTRY
    ):
        raise CheckError(
            f"{where}: expected a table with gauge and band_mm "
            "(optional transfer, requirements)"
        )
    gauge = shop.record(shop_data, "gauges", item["gauge"], f"{where}.gauge")
    resolution = shop.fact(gauge, "resolution_mm")
    low, high = band(item["band_mm"], f"{where}.band_mm")
    _within(gauge, low, high, where)
    if "transfer" in item:
        transfer = shop.record(
            shop_data, "gauges", item["transfer"], f"{where}.transfer"
        )
        _within(transfer, low, high, f"{where}.transfer")
    width = high - low
    # Floating-point noise in high - low must not decide an exact tie.
    if resolution > width and not isclose(resolution, width):
        raise CheckError(
            f"{where}: {gauge['where']} resolution {resolution:g} mm exceeds "
            f"band {low:g}–{high:g} mm width {width:g} mm"
        )


def _declared(owner: dict, shop_data: dict, where: str) -> None:
    inspected = bool(owner.get("inspection"))
    if "gauge_checks" not in owner:
        if inspected:
            raise CheckError(f"{where}: inspection has no gauge_checks")
        return
    if not inspected:
        raise CheckError(f"{where}: gauge_checks without inspection")
    declared = owner["gauge_checks"]
    if declared == "other":
        return
    if not isinstance(declared, list) or not declared:
        raise CheckError(f"{where}.gauge_checks: {_SHAPE}")
    for index, item in enumerate(declared, 1):
        _capable(item, shop_data, f"{where}.gauge_checks[{index}]")


def owners(plan: LoadedPlan):
    """Yield ``(where, table)`` for every setup and operation, numbered as printed."""
    operation_number = 0
    for setup_index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {setup_index} ({setup.get('title', 'untitled')})"
        yield where, setup
        for operation in setup["operations"]:
            operation_number += 10
            yield f"{where}, Op {operation_number}", operation


def check(plan: LoadedPlan) -> None:
    for where, owner in owners(plan):
        _declared(owner, plan.shop_data, where)
