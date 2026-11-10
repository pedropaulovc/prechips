"""Dividing-head settings: exact-first plate selection and cumulative landing error.

Arithmetic is rational on the decimal spelling of authored numbers; 360° per
revolution. Backlash, tilt and cutter access are not modelled.
"""

from __future__ import annotations

from fractions import Fraction
from math import isfinite
from typing import TYPE_CHECKING

from prechips import shop
from prechips.checks import CheckError

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_FIELDS = {"head", "tolerance_deg", "angle_deg", "positions"}


def _rational(value: object, where: str) -> Fraction:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise CheckError(f"{where}: expected a positive number")
    return Fraction(str(value))


def _nearest(value: Fraction) -> int:
    """Nearest integer; an exact half chooses the lower count."""
    low = value.numerator // value.denominator
    return low if value - low <= low + 1 - value else low + 1


def _candidates(head: dict, step: Fraction) -> list[dict]:
    """Every direct and worm-plate representation of one requested step."""
    options = []
    if "direct_index_positions" in head:
        count = head["direct_index_positions"]
        options.append(("direct", "Direct", count, Fraction(360, count)))
    if "plate_holes" in head:
        ratio = shop.fact(head, "worm_ratio")
        for plate, circles in sorted(head["plate_holes"].items()):
            options.extend(
                ("worm", plate, circle, Fraction(360, ratio * circle))
                for circle in sorted(circles)
            )
    if not options:
        raise CheckError(
            f"{head['where']}: declares neither direct_index_positions nor plate_holes"
        )
    candidates = []
    for method, plate, circle, unit in options:
        units = _nearest(step / unit)
        turns, spaces = divmod(units, circle)
        candidates.append(
            {
                "method": method,
                "plate": plate,
                "circle": circle,
                "turns": turns,
                "spaces": spaces,
                "actual": units * unit,
                "error": units * unit - step,
            }
        )
    return candidates


def setting(plan: LoadedPlan, setup: dict, where: str) -> dict | None:
    """Selected index setting for one setup, or ``None`` for ``"none"``/absent.

    Raises CheckError when the declaration cannot be computed.
    """
    declared = setup.get("indexing")
    if declared is None or declared == "none":
        return None
    field = f"{where}: indexing"
    if not isinstance(declared, dict):
        raise CheckError(f'{field}: expected "none" or a table')
    unknown = declared.keys() - _FIELDS
    if unknown:
        raise CheckError(f"{field}: unknown field(s): {', '.join(sorted(unknown))}")
    for key in ("head", "tolerance_deg"):
        if key not in declared:
            raise CheckError(f"{field}.{key}: required")
    if plan.shop is None:
        raise CheckError(f"{field}.head: requires plan.shop")
    head = shop.record(plan.shop_data, "machines", declared["head"], f"{field}.head")
    if shop.fact(head, "kind") != "dividing_head":
        raise CheckError(f"{field}.head: {head['where']} is not a dividing_head")
    tolerance = _rational(declared["tolerance_deg"], f"{field}.tolerance_deg")
    positions = declared.get("positions", 1)
    if type(positions) is not int or positions < 1:
        raise CheckError(f"{field}.positions: expected a positive integer")
    complete = "angle_deg" not in declared
    if complete and positions < 2:
        raise CheckError(f"{field}: declare angle_deg, or positions >= 2 alone")
    step = (
        Fraction(360, positions)
        if complete
        else _rational(declared["angle_deg"], f"{field}.angle_deg")
    )
    # Exact representations win; then smallest error, direct, plate, circle.
    selected = min(
        _candidates(head, step),
        key=lambda c: (
            abs(c["error"]),
            c["method"] != "direct",
            c["plate"],
            c["circle"],
        ),
    )
    # Cumulative error grows with each landing, so the last is the worst.
    selected.update(
        step=step,
        positions=positions,
        tolerance=tolerance,
        complete=complete,
        landing_error=positions * selected["error"],
    )
    if complete:
        total = positions * selected["actual"]
        selected["closure_error"] = total - 360 * _nearest(total / 360)
    return selected


def _degrees(value: Fraction) -> str:
    return f"{float(value):.4f}°"


def describe(index: dict) -> str:
    """Operator shorthand for the selected plate, crank and executed angle."""
    if index["method"] == "direct":
        source = f"Direct {index['circle']}-hole plate"
        units = "spindle turn", "hole"
    else:
        source = f"{index['plate']} {index['circle']}-hole circle"
        units = "turn", "space"
    parts = [
        f"{count} {unit}{'s' if count != 1 else ''}"
        for count, unit in zip((index["turns"], index["spaces"]), units)
        if count
    ]
    crank = " + ".join(parts) or f"0 {units[1]}s"
    if index["positions"] > 1:
        crank += f" per step × {index['positions']}"
        crank += " (full circle)" if index["complete"] else ""
    return (
        f"{source}: {crank}; {_degrees(index['actual'])} "
        f"(target {_degrees(index['step'])})"
    )


def check(plan: LoadedPlan) -> None:
    """Every setup declares indexing; landings and closure fit the tolerance."""
    for number, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {number} ({setup.get('title', 'untitled')})"
        if "indexing" not in setup:
            raise CheckError(f'{where}: missing indexing ("none" or a table)')
        index = setting(plan, setup, where)
        if index is None:
            continue
        selected = describe(index)
        tolerance = index["tolerance"]
        if abs(index["landing_error"]) > tolerance:
            raise CheckError(
                f"{where}: {selected}: landing {index['positions']} is "
                f"{float(index['landing_error']):+.6g}° off, exceeding "
                f"±{float(tolerance):g}°"
            )
        if index["complete"] and abs(index["closure_error"]) > tolerance:
            raise CheckError(
                f"{where}: {selected}: closure is "
                f"{float(index['closure_error']):+.6g}° off, exceeding "
                f"±{float(tolerance):g}°"
            )
