"""Validate authored setup-mm tool-tip motion without generating or rounding points.

This validates the motion contract only. Clearance heights are authored claims, not
physical clearance evidence: native geometry must check every approach and retract,
cutting segment, and lifted move against the part, remaining stock and fixtures.
"""

from __future__ import annotations

import math

METHOD = "manual_raster"


def _finite(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 3 and all(map(_finite, value))


def normalize(raster):
    """Return the exact explicit trajectory, or a reason withholding the entire path."""
    if not isinstance(raster, dict):
        return {"reason": "contour.raster needs an explicit setup-mm tool-tip trajectory"}
    start, safe, moves = (raster.get(key) for key in ("start_mm", "safe_z_mm", "moves"))
    if not _point(start) or not _finite(safe):
        return {"reason": "raster start_mm and safe_z_mm must be finite known setup-mm values"}
    if start[2] < safe:
        return {"reason": "raster initial tool tip must be at or above safe_z_mm"}
    if not isinstance(moves, list) or not moves:
        return {"reason": "raster needs explicit cut and clear moves"}
    previous, normalized, cuts = start, [], 0
    for index, move in enumerate(moves, 1):
        if not isinstance(move, dict) or not _point(move.get("to_mm")):
            return {"reason": f"raster move {index} needs a finite known XYZ to_mm point"}
        target, mode = move["to_mm"], move.get("mode")
        axes = [axis for axis in range(3) if previous[axis] != target[axis]]
        if mode == "cut":
            if len(axes) != 1 or axes[0] == 2:
                return {"reason": f"raster cut {index} must change exactly one X/Y axis at constant Z"}
            cuts += 1
        elif mode == "clear":
            if len(axes) != 1:
                return {"reason": f"raster clear move {index} must change exactly one axis"}
            if axes[0] != 2 and min(previous[2], target[2]) < safe:
                return {"reason": f"raster horizontal clear move {index} must be at or above safe_z_mm"}
        else:
            return {"reason": f"raster move {index} mode must be cut or clear"}
        normalized.append({"to_mm": list(target), "mode": mode})
        previous = target
    if previous[2] < safe:
        return {"reason": "raster final tool tip must be at or above safe_z_mm"}
    if not cuts:
        return {"reason": "raster needs at least one explicit horizontal cutting move"}
    return {"start_mm": list(start), "safe_z_mm": safe, "moves": normalized}


def motion_finding(rule, subject, detail, inputs, cite, blocked):
    """Read an exact finite-motion proof, never legacy axial sample counts."""
    from prechips.findings import Finding
    from prechips.rules.geometry_common import with_measurement_debts

    keys = (
        "manual_raster_status",
        "manual_raster_moves",
        "manual_raster_checked_moves",
        "manual_raster_errors",
        "tool_hits",
        "shank_hits",
        "holder_hits",
    )
    values = {"approach": METHOD, **{key: detail.get(key, "unknown") for key in keys}}
    matches = detail.get("approach") == METHOD
    hits = [values[key] for key in ("tool_hits", "shank_hits", "holder_hits")]
    minimum = detail.get("min_hits")
    if matches and isinstance(minimum, dict):
        values["min_hits"] = minimum
        hits.extend(minimum.get(key) for key in ("tool", "shank", "holder"))
    certain_hit = matches and any(_finite(value) and value > 0 for value in hits)
    trajectory = normalize(inputs.get("manual_raster"))
    moves = trajectory.get("moves")
    checked = values["manual_raster_checked_moves"]
    errors = values["manual_raster_errors"]
    complete = (
        matches
        and isinstance(moves, list)
        and isinstance(checked, int)
        and not isinstance(checked, bool)
        and checked == len(moves)
        and values["manual_raster_moves"] == len(moves)
        and checked > 0
        and errors == []
        and all(
            _finite(values[key]) and values[key] == 0
            for key in ("tool_hits", "shank_hits", "holder_hits")
        )
    )
    status = "unknown"
    message = detail.get("reason") or "exact authored manual-raster swept-tool proof is unresolved"
    if matches and (certain_hit or values["manual_raster_status"] == "error"):
        status = "error"
        message = "authored manual-raster motion meets protected part, stock or fixture material"
    elif blocked is not None:
        return blocked
    elif values["manual_raster_status"] == "pass" and complete:
        status = "pass"
        message = (
            "every authored cutting, entry, retract and index move clears the measured "
            "cutter, shank and holder against sequential stock and fixtures"
        )
    if blocked is not None and blocked.status == "error":
        return blocked
    return with_measurement_debts(
        Finding(rule, subject, status, values, cite, f"{subject}: {message}."),
        inputs.get("measurement_debts", []),
    )
