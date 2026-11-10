"""Milling-vise holding: opening, seating, grip depth, engagement and
squaring contact per hold."""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING

from prechips import lathe, shop
from prechips.checks import CheckError

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_POSITIVE = ("across_jaws_mm", "along_jaws_mm", "part_height_mm")
_NON_NEGATIVE = ("parallel_height_mm",)
_CHOICES = {
    "jaw_offset": ("centred", "balanced"),
    "fixed_jaw_face": ("machined", "as_bought", "sawn"),
    "moving_jaw_face": ("machined", "as_bought", "sawn"),
    "moving_jaw_contact": ("flat", "rod"),
}
_BALANCE = ("twin_part", "spacer")
_FIELDS = {"vise", "overhang_mm", *_POSITIVE, *_NON_NEGATIVE, *_CHOICES}
# Authored overhangs are rounded to 0.01 mm; their sum with the gripped length
# may differ from along_jaws_mm by that much without contradicting it.
_ROUNDING_MM = 0.01


def _number(value: object, where: str) -> float:
    if type(value) not in (int, float) or not isfinite(value):
        raise CheckError(f"{where}: expected a finite number")
    return float(value)


def _limit(shop_data: dict, key: str, at: str) -> float:
    try:
        return shop.limit(shop_data, key)
    except CheckError as error:
        raise CheckError(f"{at} needs {error}") from None


def _hold(shop_data: dict, value: object, where: str) -> dict:
    if not isinstance(value, dict):
        raise CheckError(f"{where}: expected a table")
    fields = _FIELDS | ({"balance"} if value.get("jaw_offset") == "balanced" else set())
    unknown = value.keys() - fields
    if unknown:
        raise CheckError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")
    missing = fields - value.keys()
    if missing:
        raise CheckError(f"{where}: missing field(s): {', '.join(sorted(missing))}")
    held = {}
    for key in _POSITIVE:
        held[key] = _number(value[key], f"{where}.{key}")
        if held[key] <= 0:
            raise CheckError(f"{where}.{key}: expected a positive number")
    for key in _NON_NEGATIVE:
        held[key] = _number(value[key], f"{where}.{key}")
        if held[key] < 0:
            raise CheckError(f"{where}.{key}: must not be negative")
    overhang = value["overhang_mm"]
    if not isinstance(overhang, list) or len(overhang) != 2:
        raise CheckError(f"{where}.overhang_mm: expected [left, right]")
    if overhang.count("rest") > 1:
        raise CheckError(f'{where}.overhang_mm: at most one side may be "rest"')
    held["overhang_mm"] = [
        None if item == "rest" else _number(item, f"{where}.overhang_mm[{side}]")
        for side, item in zip(("left", "right"), overhang)
    ]
    for key, choices in _CHOICES.items():
        if value[key] not in choices:
            raise CheckError(f"{where}.{key}: expected {' or '.join(choices)}")
        held[key] = value[key]
    if "balance" in fields:
        if value["balance"] not in _BALANCE:
            raise CheckError(f"{where}.balance: expected {' or '.join(_BALANCE)}")
        held["balance"] = value["balance"]
    held["vise"] = shop.record(shop_data, "workholding", value["vise"], f"{where}.vise")
    if shop.fact(held["vise"], "kind") != "vise":
        raise CheckError(f"{where}.vise: {held['vise']['where']} is not a vise")
    return held


def holds(shop_data: dict, setup: dict, where: str) -> list[dict]:
    """Return a setup's validated vise holds; none for lathes and ``"other"``.

    Every non-lathe setup declares ``vise_hold``: ``"other"`` (no milling vise),
    one hold table, or an array of tables for a setup that re-grips the part.
    """
    if setup.get("machine_kind") not in {"lathe", "other"}:
        raise CheckError(f"{where}: machine_kind must declare lathe or other")
    if setup.get("machine_kind") == "lathe":
        if "vise_hold" in setup:
            raise CheckError(f"{where}: lathe setups use lathe_hold, not vise_hold")
        return []
    if "vise_hold" not in setup:
        raise CheckError(f"{where}: missing vise_hold coverage")
    value = setup["vise_hold"]
    if value == "other":
        return []
    if isinstance(value, dict):
        return [_hold(shop_data, value, f"{where}.vise_hold")]
    if isinstance(value, list) and value:
        return [
            _hold(shop_data, item, f"{where}.vise_hold[{index}]")
            for index, item in enumerate(value, 1)
        ]
    raise CheckError(f'{where}.vise_hold: expected "other", a table or an array')


def _check(shop_data: dict, held: dict, at: str) -> None:
    vise = held["vise"]
    name = vise["where"]
    across = held["across_jaws_mm"]
    opening = shop.fact(vise, "opening_mm")
    if across > opening:
        raise CheckError(
            f"{at}: {across:g} mm across the jaws exceeds {name} opening {opening:g} mm"
        )
    jaw = shop.fact(vise, "jaw_height_mm")
    parallel = held["parallel_height_mm"]
    if parallel >= jaw:
        raise CheckError(
            f"{at}: parallels {parallel:g} mm are not below {name} jaw height {jaw:g} mm"
        )
    height = held["part_height_mm"]
    grip = min(height, jaw - parallel)
    minimum = _limit(shop_data, "vise_grip_min_mm", f"{at}: grip depth {grip:g} mm")
    if grip < minimum:
        raise CheckError(
            f"{at}: grip depth {grip:g} mm is below vise_grip_min_mm {minimum:g} mm"
        )
    fraction = _limit(
        shop_data, "vise_grip_fraction_min", f"{at}: grip depth {grip:g} mm"
    )
    if grip < fraction * height:
        raise CheckError(
            f"{at}: grip depth {grip:g} mm is below vise_grip_fraction_min "
            f"{fraction:g} × part height {height:g} = {fraction * height:g} mm"
        )
    # Along the jaws from the left jaw side: the part spans [-left, width + right];
    # a negative overhang is the part end's inset from that jaw side.
    width = shop.fact(vise, "jaw_width_mm")
    left, right = held["overhang_mm"]
    along = held["along_jaws_mm"]
    if left is None:
        left = along - width - right
    elif right is None:
        right = along - width - left
    elif abs(width + left + right - along) > _ROUNDING_MM:
        raise CheckError(
            f"{at}: overhangs {left:g} + {right:g} mm and {name} jaw width "
            f"{width:g} mm contradict {along:g} mm along the jaws"
        )
    start, end = max(0.0, -left), min(width, width + right)
    if end <= start:
        raise CheckError(f"{at}: the part does not reach between the jaws")
    centre = width / 2
    if held["jaw_offset"] == "centred" and not start <= centre <= end:
        raise CheckError(
            f"{at}: gripped {start:g}–{end:g} mm along the jaws misses the jaw "
            f"centre {centre:g} mm; centre the part or declare it balanced"
        )
    # A twin part sits mirrored at the other jaw end; both fit only when this
    # part lies wholly on one side of the jaw centre.
    if held.get("balance") == "twin_part" and -left < centre < width + right:
        raise CheckError(
            f"{at}: the part spans {-left:g}–{width + right:g} mm along the jaws, "
            f"across the jaw centre {centre:g} mm, so no twin fits at the other end"
        )
    fixed, moving = held["fixed_jaw_face"], held["moving_jaw_face"]
    if fixed == "sawn":
        raise CheckError(f"{at}: a sawn face must not seat against the fixed jaw")
    rod = held["moving_jaw_contact"] == "rod"
    if fixed == "machined" and moving != "machined" and not rod:
        raise CheckError(
            f"{at}: fixed-jaw face machined, moving-jaw face {moving} needs "
            "moving_jaw_contact = rod"
        )


def check(plan: LoadedPlan) -> None:
    for index, setup in enumerate(plan.data["setups"], 1):
        at = lathe.setup_label(index, setup)
        found = holds(plan.shop_data, setup, at)
        for number, held in enumerate(found, 1):
            _check(
                plan.shop_data, held, at if len(found) == 1 else f"{at} hold {number}"
            )
