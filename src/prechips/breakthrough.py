"""Declared through holes against the tool's point or lead (full Ø at the exit).

Every twist-drilled hole (``drilling = "twist_drill"``) declares ``hole_exit``:
``"blind"``, ``"other"`` (through, no tip depth stated: fed until it breaks
through) or ``{ tip_z_mm }``, the tool tip's Z with Z0 at the hole's exit face
(negative past it). Any other tooled operation, such as a reamer, may declare a
``hole_exit`` table too. The tip must pass the exit face by the tool's lead,
the length behind its tip before the full diameter: a twist drill's point,
``(diameter_mm / 2) / tan(point_deg / 2)`` from the tool's ``point_deg``, or
any other tool's stated ``lead_mm`` (a reamer's chamfer).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from prechips.checks import CheckError, positive_mm
from prechips.pecking import DRILLING

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

_OPT_OUTS = ("blind", "other")


def point_length_mm(diameter: float, point_deg: float) -> float:
    """Axial length of a twist drill's point: tip to full diameter."""
    return diameter / 2 / math.tan(math.radians(point_deg) / 2)


def _number(value: object, where: str) -> float:
    if type(value) in (int, float) and math.isfinite(value):
        return float(value)
    raise CheckError(f"{where}: expected a number in mm")


def _lead(tool: dict, twist_drill: bool, where: str) -> tuple[float, str]:
    """The tool's lead in mm and how it was found."""
    name = f"tool {tool['id']!r}"
    if not twist_drill:
        if "lead_mm" not in tool:
            raise CheckError(f"{where}: {name} must state lead_mm (its chamfer)")
        lead = positive_mm(tool["lead_mm"], f"{name} lead_mm")
        return lead, f"lead_mm {lead:g}"
    for key in ("diameter_mm", "point_deg"):
        if key not in tool:
            raise CheckError(f"{where}: the twist drill {name} must state {key}")
    diameter = positive_mm(tool["diameter_mm"], f"{name} diameter_mm")
    point = tool["point_deg"]
    if type(point) not in (int, float) or not 0 < point < 180:
        raise CheckError(f"{name} point_deg: expected an angle above 0 below 180")
    lead = point_length_mm(diameter, point)
    return lead, f"Ø{diameter:g} mm {point:g}° point, {lead:.3f} mm long"


def _check_exit(hole_exit: object, tool: dict, twist_drill: bool, where: str) -> None:
    if twist_drill and hole_exit in _OPT_OUTS:
        return
    if not isinstance(hole_exit, dict) or hole_exit.keys() != {"tip_z_mm"}:
        expected = '"blind", "other" or ' if twist_drill else ""
        raise CheckError(f"{where}.hole_exit: expected {expected}{{ tip_z_mm }}")
    past = -_number(hole_exit["tip_z_mm"], f"{where}.hole_exit.tip_z_mm")
    lead, source = _lead(tool, twist_drill, where)
    if past < lead:
        raise CheckError(
            f"{where}: the tip, {past:g} mm past the exit face, is short of the "
            f"tool's lead ({source}): the hole is not full Ø at its exit"
        )


def check(plan: LoadedPlan) -> None:
    """Refuse a through hole not full Ø at its exit; emit nothing on a pass."""
    tools = {tool["id"]: tool for tool in plan.data["tools"]}
    number = 0
    for index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {index} ({setup.get('title', 'untitled')})"
        for operation in setup["operations"]:
            number += 10
            op_where = f"{where}, Op {number}"
            if not operation.get("tool"):
                if "hole_exit" in operation:
                    raise CheckError(f"{op_where}: hole_exit declared without a tool")
                continue
            drilling = operation.get("drilling")
            if drilling not in DRILLING:
                raise CheckError(
                    f'{op_where}.drilling: expected "twist_drill" or "none"'
                )
            twist_drill = drilling == "twist_drill"
            if "hole_exit" not in operation:
                if twist_drill:
                    raise CheckError(
                        f'{op_where}: a twist-drilled hole requires hole_exit ("blind", '
                        '"other" or { tip_z_mm })'
                    )
                continue
            tool = tools[operation["tool"]]
            _check_exit(operation["hole_exit"], tool, twist_drill, op_where)
