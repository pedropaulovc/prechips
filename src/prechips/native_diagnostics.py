"""Publish selected native diagnostics without changing geometry or rule operands.

The six-decimal, positive-zero representation matches ``freecad_job._r`` for
native witness coordinates, areas and volumes. Apply it only after evaluating
raw facts: contact areas/bounds and saw witnesses also feed safety decisions.
"""

from __future__ import annotations

import math
from typing import Any

_PICKUP_MODELS = ("transverse_finder_v1", "arriving_top_v1")
_CONTACT_AREAS = (
    "contact_area_mm2",
    "uncovered_area_mm2",
    "patch_area_mm2",
)


def _diagnostic(value: Any) -> Any:
    # Preserve unknown/malformed facts; nonfinite numbers still fail canonical JSON.
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    if not math.isfinite(value):
        return value
    rounded = round(float(value), 6)
    return 0.0 if rounded == 0 else rounded


def _coordinates(record: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        points = record.get(field)
        if isinstance(points, list):
            record[field] = [_diagnostic(point) for point in points]


def publish_native_diagnostics(value: Any) -> Any:
    """Copy JSON containers and canonicalize only identified native diagnostics.

    Raw kernel facts and ``Finding.numbers`` must remain the operands for every
    classification, comparison and minimum selection. This publication projection
    never rounds scalar distances, authored requests, targets or tool dimensions.
    """
    if isinstance(value, list):
        return [publish_native_diagnostics(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: publish_native_diagnostics(item) for key, item in value.items()}
    if value.get("model") in _PICKUP_MODELS:
        contact = result.get("resolved_contact")
        if (
            value.get("model") == "arriving_top_v1"
            and isinstance(contact, dict)
            and contact.get("contact_model") == "flat_end_projection_v1"
        ):
            _coordinates(contact, ("patch_bbox_mm",))
            for field in _CONTACT_AREAS:
                if field in contact:
                    contact[field] = _diagnostic(contact[field])
        path = result.get("path")
        if isinstance(path, dict) and isinstance(path.get("legs"), list):
            for leg in path["legs"]:
                if not isinstance(leg, dict) or not isinstance(leg.get("components"), list):
                    continue
                for component in leg["components"]:
                    if isinstance(component, dict) and "swept_volume_mm3" in component:
                        component["swept_volume_mm3"] = _diagnostic(component["swept_volume_mm3"])
    if (
        value.get("model") == "finite_disk_v1"
        and value.get("source") == "finite_occupied_sweeps"
        and value.get("scope") == "machining_trajectory"
        and value.get("frame") == "setup"
    ):
        minimum = result.get("minimum")
        if isinstance(minimum, dict):
            _coordinates(minimum, ("from_mm", "to_mm"))
        sweeps = result.get("sweeps")
        if isinstance(sweeps, list):
            for sweep in sweeps:
                minimum = sweep.get("minimum") if isinstance(sweep, dict) else None
                if isinstance(minimum, dict):
                    _coordinates(minimum, ("from_mm", "to_mm"))
    return result
