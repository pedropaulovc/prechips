"""Gauge capability: every declared inspection band fits its named gauge.

A setup or operation with ``inspection`` text declares ``gauge_checks``: either
``"other"`` (non-dimensional acceptance such as finish, fit-up or visual) or one
``{ gauge, band_mm }`` entry per dimensional limit the text states. The gauge's
``range_mm`` must contain both band ends and its ``resolution_mm`` must not exceed
the band width (high - low).
"""

from __future__ import annotations

from math import isclose, isfinite
from typing import TYPE_CHECKING

from prechips import shop
from prechips.checks import CheckError

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_SHAPE = 'expected "other" or a nonempty array of { gauge, band_mm } tables'


def _band(value: object, where: str) -> tuple[float, float]:
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


def _capable(item: object, shop_data: dict, where: str) -> None:
    if not isinstance(item, dict) or item.keys() != {"gauge", "band_mm"}:
        raise CheckError(f"{where}: expected a table with gauge and band_mm")
    gauge = shop.record(shop_data, "gauges", item["gauge"], f"{where}.gauge")
    span_low, span_high = shop.fact(gauge, "range_mm")
    resolution = shop.fact(gauge, "resolution_mm")
    low, high = _band(item["band_mm"], f"{where}.band_mm")
    if low < span_low or high > span_high:
        raise CheckError(
            f"{where}: band {low:g}–{high:g} mm is outside {gauge['where']} "
            f"range {span_low:g}–{span_high:g} mm"
        )
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


def check(plan: LoadedPlan) -> None:
    operation_number = 0
    for setup_index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {setup_index} ({setup.get('title', 'untitled')})"
        _declared(setup, plan.shop_data, where)
        for operation in setup["operations"]:
            operation_number += 10
            _declared(operation, plan.shop_data, f"{where}, Op {operation_number}")
