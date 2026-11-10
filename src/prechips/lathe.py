"""Lathe workholding: grip capacity and unsupported stick-out per setup."""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from prechips import shop
from prechips.checks import CheckError

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_NUMBERS = (
    "grip_diameter_mm",
    "stock_diameter_mm",
    "stickout_mm",
    "minimum_diameter_mm",
)
_SUPPORTS = {"none", "tailstock", "steady_rest"}
# turning_support.kind -> the lathe_hold.support it implies.
_TURNING_SUPPORT = {
    "chuck_only": "none",
    "tailstock": "tailstock",
    "follower": "tailstock",
}


def setup_label(index: int, setup: dict) -> str:
    return f"setup {index} ({setup.get('title', 'untitled')})"


def hold(shop_data: dict, setup: dict, where: str) -> dict | None:
    """Return a lathe setup's validated hold, or None when not applicable.

    Non-lathe setups and the explicit ``lathe_hold = "other"`` opt-out return
    None; a lathe setup without ``lathe_hold`` is refused. The returned table
    has float numbers and ``chuck`` resolved to its shop workholding record.
    """
    kind = setup.get("machine_kind")
    if kind not in {"lathe", "other"}:
        raise CheckError(f"{where}: machine_kind must declare lathe or other")
    if kind == "other":
        if "lathe_hold" in setup:
            raise CheckError(f"{where}: machine_kind other contradicts lathe_hold")
        return None
    if "lathe_hold" not in setup:
        raise CheckError(f"{where}: missing lathe_hold coverage")
    value = setup["lathe_hold"]
    if value == "other":
        return None
    if not isinstance(value, dict):
        raise CheckError(f'{where}.lathe_hold: expected "other" or a table')
    expected = {"chuck", "support", *_NUMBERS}
    unknown = value.keys() - expected
    if unknown:
        raise CheckError(
            f"{where}.lathe_hold: unknown field(s): {', '.join(sorted(unknown))}"
        )
    missing = expected - value.keys()
    if missing:
        raise CheckError(
            f"{where}.lathe_hold: missing field(s): {', '.join(sorted(missing))}"
        )
    result = {}
    for key in _NUMBERS:
        number = value[key]
        if type(number) not in (int, float) or not isfinite(number) or number <= 0:
            raise CheckError(f"{where}.lathe_hold.{key}: expected a positive number")
        result[key] = float(number)
    if value["support"] not in _SUPPORTS:
        raise CheckError(
            f"{where}.lathe_hold.support: expected none, tailstock or steady_rest"
        )
    result["support"] = value["support"]
    largest = max(result["grip_diameter_mm"], result["minimum_diameter_mm"])
    if result["stock_diameter_mm"] < largest:
        raise CheckError(
            f"{where}.lathe_hold: stock_diameter_mm {result['stock_diameter_mm']:g} "
            f"mm is smaller than grip or minimum diameter {largest:g} mm"
        )
    result["chuck"] = shop.record(
        shop_data, "workholding", value["chuck"], f"{where}.lathe_hold.chuck"
    )
    return result


def check(plan: LoadedPlan) -> None:
    for index, setup in enumerate(plan.data["setups"], 1):
        at = setup_label(index, setup)
        held = hold(plan.shop_data, setup, at)
        if held is None:
            continue
        chuck = held["chuck"]
        grip = held["grip_diameter_mm"]
        if shop.fact(chuck, "kind") == "collet":
            sizes = shop.fact(chuck, "grip_sizes_mm")
            if not any(abs(grip - size) <= 1e-6 for size in sizes):
                listed = ", ".join(f"{size:g}" for size in sizes)
                raise CheckError(
                    f"{at}: grip Ø{grip:g} mm is not a {chuck['where']} size "
                    f"({listed} mm)"
                )
        else:
            low, high = shop.fact(chuck, "grip_range_mm")
            if not low <= grip <= high:
                raise CheckError(
                    f"{at}: grip Ø{grip:g} mm is outside {chuck['where']} grip "
                    f"range {low:g}–{high:g} mm"
                )
        turning = setup.get("turning_support")
        implied = (
            _TURNING_SUPPORT.get(turning.get("kind"))
            if isinstance(turning, dict)
            else None
        )
        if implied is not None and implied != held["support"]:
            raise CheckError(
                f"{at}: lathe_hold.support {held['support']} contradicts "
                f"turning_support.kind {turning['kind']}"
            )
        if held["support"] != "none":
            continue
        ratio = shop.limit(plan.shop_data, "stickout_ld_max")
        minimum = held["minimum_diameter_mm"]
        allowed = ratio * minimum
        stickout = held["stickout_mm"]
        if stickout > allowed:
            raise CheckError(
                f"{at}: unsupported stickout {stickout:g} mm exceeds "
                f"{ratio:g} × Ø{minimum:g} = {allowed:g} mm"
            )
