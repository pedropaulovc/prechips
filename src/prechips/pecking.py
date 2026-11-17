"""Declared drill pecking against hole depth over drill diameter (L/D).

Every operation with a tool declares ``drilling``: ``"twist_drill"`` for a
twist-drilled hole (mill, drill press or lathe tailstock alike), or ``"none"``
(spots, countersinks, reamers, end mills, taps, saws, turning tools). A
twist-drilled hole declares ``hole_depth_mm`` and ``peck``: ``"none"`` or a peck
table; ``peck_reason`` justifies pecking a hole shallow enough to need none.
The drill diameter is the operation tool's ``diameter_mm``. Bands and the step
limit live in the ``[pecking]`` section of turning.toml: rules of thumb, not
standards, with no material shift (no cited source gives one).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prechips.checks import CheckError, positive_mm

if TYPE_CHECKING:
    from prechips.traveler import LoadedPlan

# Lightest to heaviest: a heavier strategy always satisfies a lighter band.
STRATEGIES = ("none", "chip_break", "full")
DRILLING = ("twist_drill", "none")
_PECK_KEYS = {"step_mm", "retract"}
_HOLE_FIELDS = {"hole_depth_mm", "peck", "peck_reason"}
# Relative slack on band edges and the step limit: a hole of exactly 3 D in
# inch sizes (9.525 / 3.175 mm) divides to 3.0000000000000004.
_EDGE = 1e-9


def _above(value: float, edge: float) -> bool:
    return value > edge * (1 + _EDGE)


def required_strategy(ld: float, bands: dict) -> str:
    """The lightest strategy a hole of this L/D needs; refuses above ``max_ld``."""
    if _above(ld, bands["max_ld"]):
        raise CheckError(
            f"L/D {ld:.3g} exceeds max_ld {bands['max_ld']:g}: needs deep-hole "
            "tooling, not twist-drill pecking"
        )
    if _above(ld, bands["full_retract_above_ld"]):
        return "full"
    if _above(ld, bands["chip_break_above_ld"]):
        return "chip_break"
    return "none"


def _bands(config: dict) -> dict:
    bands = config["pecking"]
    order = ("chip_break_above_ld", "full_retract_above_ld", "max_ld")
    if not bands[order[0]] < bands[order[1]] < bands[order[2]]:
        raise CheckError(f"pecking: expected {' < '.join(order)}")
    return bands


def _declared(peck: object, where: str) -> tuple[str, float | None]:
    """The declared strategy and step (mm, or None for no peck)."""
    if peck == "none":
        return "none", None
    if not isinstance(peck, dict):
        raise CheckError(f'{where}.peck: expected "none" or a peck table')
    if peck.keys() != _PECK_KEYS:
        raise CheckError(f"{where}.peck: expected exactly step_mm and retract")
    retract = peck["retract"]
    if retract not in STRATEGIES[1:]:
        raise CheckError(f"{where}.peck.retract: expected chip_break or full")
    return retract, positive_mm(peck["step_mm"], f"{where}.peck.step_mm")


def _reason(operation: dict, where: str) -> str | None:
    reason = operation.get("peck_reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        raise CheckError(f"{where}.peck_reason: expected the stated justification")
    return reason


def _check_hole(operation: dict, tools: dict, bands: dict, where: str) -> None:
    if "peck" not in operation:
        raise CheckError(
            f'{where}: a twist-drilled hole requires peck ("none" or a table)'
        )
    declared, step = _declared(operation["peck"], where)
    reason = _reason(operation, where)
    if "hole_depth_mm" not in operation:
        raise CheckError(f"{where}: missing hole_depth_mm")
    depth = positive_mm(operation["hole_depth_mm"], f"{where}.hole_depth_mm")
    tool = tools[operation["tool"]]
    if "diameter_mm" not in tool:
        raise CheckError(f"{where}: the operation tool must declare diameter_mm")
    diameter = positive_mm(tool["diameter_mm"], f"tool {tool['id']!r} diameter_mm")
    ld = depth / diameter
    hole = f"{where}: hole {depth:g} mm deep, Ø{diameter:g} mm"
    try:
        required = required_strategy(ld, bands)
    except CheckError as error:
        raise CheckError(f"{hole}: {error}") from error
    hole = f"{hole}, L/D {ld:.3g}"
    if STRATEGIES.index(declared) < STRATEGIES.index(required):
        key = "full_retract" if required == "full" else "chip_break"
        raise CheckError(
            f"{hole}: peck {declared!r} is too light; above {key}_above_ld "
            f"{bands[f'{key}_above_ld']:g} it needs {required!r}"
        )
    shallow = declared != "none" and required == "none"
    if shallow and reason is None:
        raise CheckError(
            f"{hole}: pecking at or below chip_break_above_ld "
            f'{bands["chip_break_above_ld"]:g} needs peck_reason, or peck = "none"'
        )
    if reason is not None and not shallow:
        raise CheckError(
            f"{where}.peck_reason: only justifies pecking at or below "
            f"chip_break_above_ld {bands['chip_break_above_ld']:g}"
        )
    if step is None:
        return
    limit = bands["step_max_diameters"] * diameter
    if _above(step, limit):
        raise CheckError(
            f"{hole}: peck step {step:g} mm exceeds step_max_diameters "
            f"{bands['step_max_diameters']:g} × Ø{diameter:g} = {limit:g} mm"
        )


def check(plan: LoadedPlan, config: dict) -> None:
    """Refuse missing, too-light or over-long pecking; emit nothing on a pass."""
    bands = _bands(config)
    tools = {tool["id"]: tool for tool in plan.data["tools"]}
    number = 0
    for index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {index} ({setup.get('title', 'untitled')})"
        for operation in setup["operations"]:
            number += 10
            op_where = f"{where}, Op {number}"
            declared = _HOLE_FIELDS & operation.keys()
            if not operation.get("tool"):
                if declared or "drilling" in operation:
                    raise CheckError(f"{op_where}: drilling declared without a tool")
                continue
            drilling = operation.get("drilling")
            if drilling not in DRILLING:
                raise CheckError(
                    f'{op_where}.drilling: expected "twist_drill" or "none"'
                )
            if drilling == "none":
                if declared:
                    raise CheckError(
                        f'{op_where}: drilling "none" takes no '
                        f"{', '.join(sorted(declared))}"
                    )
                continue
            _check_hole(operation, tools, bands, op_where)
