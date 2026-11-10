"""Machine capacity: lathe swing/length and mill travel/spindle-to-table range."""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from prechips import lathe, shop
from prechips.checks import CheckError

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_ENVELOPE = (
    "x_span_mm",
    "y_span_mm",
    "work_top_mm",
    "deepest_cut_mm",
    "longest_tool_mm",
    "shortest_tool_mm",
)


def _machine(shop_data: dict, setup: dict, kind: str, where: str) -> dict:
    if "machine_ref" not in setup:
        raise CheckError(f"{where}: machine capacity requires machine_ref")
    machine = shop.record(
        shop_data, "machines", setup["machine_ref"], f"{where}.machine_ref"
    )
    if shop.fact(machine, "kind") != kind:
        raise CheckError(f"{where}: {machine['where']} is not a {kind}")
    return machine


def _stack(value: object, where: str) -> float:
    """A number, or a nonempty array of numbers (a stack) used as its sum."""
    items = value if isinstance(value, list) and value else [value]
    if any(type(item) not in (int, float) or not isfinite(item) for item in items):
        raise CheckError(f"{where}: expected a number or a nonempty array of numbers")
    return float(sum(items))


def _envelope(value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise CheckError(f'{where}: expected "other" or a table')
    unknown = value.keys() - set(_ENVELOPE)
    if unknown:
        raise CheckError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
    missing = set(_ENVELOPE) - value.keys()
    if missing:
        raise CheckError(f"{where}: missing field(s): {', '.join(sorted(missing))}")
    result = {key: _stack(value[key], f"{where}.{key}") for key in _ENVELOPE}
    if min(result.values()) < 0:
        raise CheckError(
            f"{where}: spans, heights and tool lengths must not be negative"
        )
    if result["deepest_cut_mm"] > result["work_top_mm"]:
        raise CheckError(f"{where}: deepest_cut_mm must not exceed work_top_mm")
    if result["shortest_tool_mm"] > result["longest_tool_mm"]:
        raise CheckError(f"{where}: shortest_tool_mm must not exceed longest_tool_mm")
    return result


def _check_lathe(shop_data: dict, setup: dict, held: dict, at: str) -> None:
    machine = _machine(shop_data, setup, "lathe", at)
    name = machine["where"]
    chuck = held["chuck"]
    body = shop.fact(chuck, "body_diameter_mm")
    stock = held["stock_diameter_mm"]
    swing = shop.fact(machine, "swing_over_bed_mm")
    if max(stock, body) > swing:
        raise CheckError(
            f"{at}: stock Ø{stock:g} mm / {chuck['where']} body Ø{body:g} mm "
            f"exceeds {name} swing over bed {swing:g} mm"
        )
    slide = shop.fact(machine, "swing_over_cross_slide_mm")
    if stock > slide:
        raise CheckError(
            f"{at}: stock Ø{stock:g} mm exceeds {name} swing over cross slide "
            f"{slide:g} mm"
        )
    stickout = held["stickout_mm"]
    length = shop.fact(chuck, "body_length_mm")
    centres = shop.fact(machine, "between_centres_mm")
    if stickout + length > centres:
        raise CheckError(
            f"{at}: stickout {stickout:g} + chuck body length {length:g} = "
            f"{stickout + length:g} mm exceeds {name} between centres {centres:g} mm"
        )


def _check_mill(shop_data: dict, setup: dict, envelope: dict, at: str) -> None:
    machine = _machine(shop_data, setup, "mill", at)
    name = machine["where"]
    travel = shop.fact(machine, "travel_mm")
    for axis in ("x", "y"):
        span = envelope[f"{axis}_span_mm"]
        if span > travel[axis]:
            raise CheckError(
                f"{at}: {axis.upper()} span {span:g} mm exceeds {name} "
                f"{axis.upper()} travel {travel[axis]:g} mm"
            )
    lowest, highest = shop.fact(machine, "spindle_to_table_mm")
    clearance = shop.limit(shop_data, "tool_change_clearance_mm")
    top = envelope["work_top_mm"]
    longest = envelope["longest_tool_mm"]
    # Tool change: the longest tool and its insertion clearance above the work.
    needed = top + longest + clearance
    if needed > highest:
        raise CheckError(
            f"{at}: work top {top:g} + longest tool {longest:g} + tool-change "
            f"clearance {clearance:g} = {needed:g} mm exceeds {name} "
            f"spindle-to-table maximum {highest:g} mm"
        )
    # Reach: the spindle nose must come down far enough for the shortest tool.
    deepest = envelope["deepest_cut_mm"]
    shortest = envelope["shortest_tool_mm"]
    nose = deepest + shortest
    if nose < lowest:
        raise CheckError(
            f"{at}: deepest cut {deepest:g} + shortest tool {shortest:g} = "
            f"{nose:g} mm is below {name} spindle-to-table minimum {lowest:g} mm"
        )


def check(plan: LoadedPlan) -> None:
    for index, setup in enumerate(plan.data["setups"], 1):
        at = lathe.setup_label(index, setup)
        if setup.get("machine_kind") == "lathe":
            if "envelope" in setup:
                raise CheckError(f"{at}: lathe setups use lathe_hold, not envelope")
            held = lathe.hold(plan.shop_data, setup, at)
            if held is not None:
                _check_lathe(plan.shop_data, setup, held, at)
            continue
        lathe.hold(plan.shop_data, setup, at)
        if "envelope" not in setup:
            raise CheckError(f"{at}: missing envelope coverage")
        if setup["envelope"] == "other":
            continue
        envelope = _envelope(setup["envelope"], f"{at}.envelope")
        _check_mill(plan.shop_data, setup, envelope, at)
