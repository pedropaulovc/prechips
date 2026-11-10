"""Tool sizing: declared operation tool diameters against drawing bands or tap drills.

Every operation with a tool declares ``sizing``: ``"other"`` or a table. The
check compares the selected tool only; it never searches for a nearer tool.
"""

from math import isfinite

from prechips.checks import CheckError
from prechips.traveler import LoadedPlan

# Archived op_chain criterion: tap-drill lengths agree within absolute 1e-6 mm.
TAP_DRILL_TOLERANCE_MM = 1e-6


def _positive(value: object, where: str) -> float:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise CheckError(f"{where}: expected a positive number in mm")
    return float(value)


def _keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = table.keys() - allowed
    if unknown:
        raise CheckError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")


def _tool_size(tool: dict, field: str, where: str) -> float:
    if field not in tool:
        raise CheckError(f"{where}: tool {tool['id']!r} {field} is not declared")
    return tool[field]


def check(plan: LoadedPlan) -> None:
    tools = {tool["id"]: tool for tool in plan.data["tools"]}
    for tool in tools.values():
        for field in ("diameter_mm", "tap_drill_mm"):
            if field in tool:
                _positive(tool[field], f"tool {tool['id']!r} {field}")
    number = 0
    for setup_index, setup in enumerate(plan.data["setups"], 1):
        where = f"setup {setup_index} ({setup['title']})"
        for operation in setup["operations"]:
            number += 10
            op_where = f"{where}, Op {number}"
            tool_id = operation.get("tool")
            sizing = operation.get("sizing")
            if not tool_id:
                if sizing is not None:
                    raise CheckError(f"{op_where}: sizing declared without a tool")
                continue
            if sizing is None:
                raise CheckError(
                    f"{op_where}: tool {tool_id!r} requires sizing "
                    '("other", band or tap_drill)'
                )
            if sizing == "other":
                continue
            if not isinstance(sizing, dict):
                raise CheckError(f'{op_where}: sizing must be "other" or a table')
            _check_sizing(sizing, tools[tool_id], tools, f"{op_where}, sizing")


def _check_sizing(sizing: dict, tool: dict, tools: dict, where: str) -> None:
    kind = sizing.get("kind")
    if kind == "band":
        _keys(sizing, {"kind", "band_mm"}, where)
        band = sizing.get("band_mm")
        if not isinstance(band, list) or len(band) != 2:
            raise CheckError(f"{where}.band_mm: expected [low, high] in mm")
        low = _positive(band[0], f"{where}.band_mm")
        high = _positive(band[1], f"{where}.band_mm")
        if low > high:
            raise CheckError(f"{where}.band_mm: reversed band {low:.6g}–{high:.6g} mm")
        diameter = _tool_size(tool, "diameter_mm", where)
        if low <= diameter <= high:
            return
        raise CheckError(
            f"{where}: tool {tool['id']!r} diameter {diameter:.6g} mm is outside "
            f"band {low:.6g}–{high:.6g} mm"
        )
    if kind == "tap_drill":
        _keys(sizing, {"kind", "tap"}, where)
        tap_id = sizing.get("tap")
        if not isinstance(tap_id, str) or tap_id not in tools:
            raise CheckError(f"{where}.tap: unknown tool {tap_id!r}")
        tap_drill = _tool_size(tools[tap_id], "tap_drill_mm", where)
        diameter = _tool_size(tool, "diameter_mm", where)
        if abs(diameter - tap_drill) <= TAP_DRILL_TOLERANCE_MM:
            return
        raise CheckError(
            f"{where}: tool {tool['id']!r} diameter {diameter:.6g} mm does not "
            f"match tap {tap_id!r} tap drill {tap_drill:.6g} mm"
        )
    raise CheckError(f"{where}.kind: expected band or tap_drill")
