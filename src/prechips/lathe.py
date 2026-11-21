"""Lathe workholding: grip capacity and unsupported stick-out per setup."""

from __future__ import annotations

from math import inf, isfinite
from typing import TYPE_CHECKING

from prechips import shop
from prechips.checks import CheckError, positive_mm
from prechips.turning import step_sequence

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
    unknown = value.keys() - expected - {"load_diameter_mm"}
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
    if "load_diameter_mm" in value:
        result["load_diameter_mm"] = positive_mm(
            value["load_diameter_mm"], f"{where}.lathe_hold.load_diameter_mm"
        )
        if result["support"] != "none":
            raise CheckError(
                f"{where}.lathe_hold.load_diameter_mm: a step-turned hold is "
                "unsupported (support none)"
            )
        if not (
            result["minimum_diameter_mm"]
            <= result["load_diameter_mm"]
            <= result["stock_diameter_mm"]
        ):
            raise CheckError(
                f"{where}.lathe_hold.load_diameter_mm: expected between "
                "minimum_diameter_mm and stock_diameter_mm"
            )
    result["chuck"] = shop.record(
        shop_data, "workholding", value["chuck"], f"{where}.lathe_hold.chuck"
    )
    if shop.fact(result["chuck"], "kind") not in {"chuck", "collet"}:
        raise CheckError(
            f"{where}.lathe_hold.chuck: {result['chuck']['where']} "
            "is not a chuck or collet"
        )
    return result


def _number(value: object, where: str) -> float:
    if type(value) in (int, float):
        try:
            number = float(value)
        except OverflowError:  # TOML integers are unbounded
            number = inf
        if isfinite(number):
            return number
    raise CheckError(f"{where}: expected a finite number")


def _turning_load(operation: dict, load: float, chuck_z: float, at: str) -> None:
    """A turning operation under a step-turned hold loads no thinner section.

    A stepped operation names its load section and runs toward the chuck; a
    plain pass is judged at its own model section, the smaller of its end
    and minimum diameters, so a pass over the finished length refuses.
    """
    cuts = operation.get("turning_cuts")
    if not isinstance(cuts, list) or not cuts:
        raise CheckError(f"{at}: missing nonempty turning_cuts")
    step = operation.get("turning_step")
    if step is not None:
        if not isinstance(step, dict):
            raise CheckError(f"{at}.turning_step: expected a table")
        section = positive_mm(
            step.get("load_diameter_mm"), f"{at}.turning_step.load_diameter_mm"
        )
        if section < load:
            raise CheckError(
                f"{at}: turning_step loads Ø{section:g} mm, under the hold's "
                f"Ø{load:g} mm load section"
            )
        problem = step_sequence(cuts, section)
        if problem is not None:
            raise CheckError(f"{at}.{problem}")
    for index, cut in enumerate(cuts, 1):
        if not isinstance(cut, dict):
            raise CheckError(f"{at}, cut {index}: expected a table")
        where = f"{at}, cut {cut.get('name', index)!r}"
        if step is not None:
            start = _number(cut.get("start_z_mm"), f"{where}.start_z_mm")
            end = _number(cut.get("end_z_mm"), f"{where}.end_z_mm")
            if abs(start - chuck_z) <= abs(end - chuck_z):
                raise CheckError(
                    f"{where}: runs away from the chuck, a return pass over the "
                    "step-turned length"
                )
            continue
        section = min(
            positive_mm(cut.get(key), f"{where}.{key}")
            for key in ("end_diameter_mm", "minimum_diameter_mm")
        )
        if section < load:
            raise CheckError(
                f"{where}: a plain pass at Ø{section:g} mm loads less than the "
                f"hold's Ø{load:g} mm load section; turn it in steps toward the "
                "chuck (turning_step)"
            )


def _operation_loads(setup: dict, held: dict | None, at: str, first: int) -> None:
    """Refuse a step-turned hold whose operations load a thinner section.

    Under ``lathe_hold.load_diameter_mm`` every operation with a tool states
    the least section between the jaws and its cut (``load_diameter_mm``;
    turning operations through their cuts), so a later cut on the finished
    slender length, such as a chamfer or a single-point thread, refuses.
    """
    load = held.get("load_diameter_mm") if held is not None else None
    chuck_z = None
    if load is not None:
        support = setup.get("turning_support")
        if not isinstance(support, dict) or support.get("kind") != "chuck_only":
            raise CheckError(
                f"{at}: a step-turned hold (lathe_hold.load_diameter_mm) needs "
                "turning_support chuck_only"
            )
        chuck_z = _number(support.get("chuck_z_mm"), f"{at}.turning_support.chuck_z_mm")
    for offset, operation in enumerate(setup.get("operations", [])):
        op_at = f"{at}, Op {first + 10 * (offset + 1)}"
        declared = "load_diameter_mm" in operation
        if load is None:
            if declared:
                raise CheckError(
                    f"{op_at}: load_diameter_mm needs a step-turned hold "
                    "(lathe_hold.load_diameter_mm)"
                )
            continue
        if operation.get("cut_kind") == "longitudinal_turning":
            if declared:
                raise CheckError(
                    f"{op_at}: a turning operation states its load section in "
                    "turning_step, not load_diameter_mm"
                )
            _turning_load(operation, load, chuck_z, op_at)
            continue
        if "tool" not in operation:
            if declared:
                raise CheckError(f"{op_at}: load_diameter_mm without a tool")
            continue
        if not declared:
            raise CheckError(
                f"{op_at}: missing load_diameter_mm, the least section between "
                "the jaws and this operation's cut under a step-turned hold"
            )
        section = positive_mm(
            operation["load_diameter_mm"], f"{op_at}.load_diameter_mm"
        )
        if section < load:
            raise CheckError(
                f"{op_at}: cuts through Ø{section:g} mm, under the hold's "
                f"Ø{load:g} mm load section: the step-turned length would be cut "
                "again"
            )


def check(plan: LoadedPlan) -> None:
    operation_number = 0
    for index, setup in enumerate(plan.data["setups"], 1):
        at = setup_label(index, setup)
        first = operation_number
        operation_number += 10 * len(setup.get("operations", []))
        held = hold(plan.shop_data, setup, at)
        _operation_loads(setup, held, at, first)
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
        if "load_diameter_mm" in held:
            load = held["load_diameter_mm"]
            allowed = ratio * load
            stickout = held["stickout_mm"]
            if stickout > allowed:
                raise CheckError(
                    f"{at}: unsupported stickout {stickout:g} mm exceeds "
                    f"{ratio:g} × Ø{load:g} = {allowed:g} mm (the step-turned "
                    "hold's load section)"
                )
            continue
        minimum = held["minimum_diameter_mm"]
        allowed = ratio * minimum
        stickout = held["stickout_mm"]
        if stickout > allowed:
            raise CheckError(
                f"{at}: unsupported stickout {stickout:g} mm exceeds "
                f"{ratio:g} × Ø{minimum:g} = {allowed:g} mm"
            )
