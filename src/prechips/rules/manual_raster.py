"""Validate authored setup-mm tool-tip motion without generating or rounding points.

This validates the motion contract only. Clearance heights are authored claims, not
physical clearance evidence: native geometry must check every approach and retract,
cutting segment, and lifted move against the part, remaining stock and fixtures.
"""

from __future__ import annotations

import math

METHOD = "manual_ball_raster"


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


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
