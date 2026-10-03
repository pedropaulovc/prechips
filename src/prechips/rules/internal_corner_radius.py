"""Concave claimed-face edges perpendicular to the setup tool axis."""

from prechips.findings import Finding
from prechips.rules.geometry_common import fact_reason, op_contexts
from prechips.rules.resolution import number


def evaluate(bundle):
    rows = []
    for setup, op, _, detail, inputs, cite, blocked in op_contexts(
        bundle, "internal_corner_radius", ("radius_mm",), stock=False
    ):
        if blocked:
            rows.append(blocked)
            continue
        subject = f"{setup['id']}:{op['op']}"
        radii = detail.get("corner_radii_mm", "unknown")
        radius = inputs["radius_mm"]
        values = {"corner_radii_mm": radii, "tool_radius_mm": radius}
        status, message = (
            "unknown",
            fact_reason(detail, ("corner_radii_mm",), "concave edge radii are unresolved"),
        )
        if isinstance(radii, list) and all(number(value) and value >= 0 for value in radii):
            if not radii:
                status, message = (
                    "not_applicable",
                    "claimed faces have no concave edges perpendicular to the tool axis",
                )
            else:
                smallest = min(radii)
                values["minimum_corner_radius_mm"] = smallest
                # STEP exports round radii to 5–6 significant digits.
                status = "pass" if smallest >= radius - 0.005 else "error"
                message = (
                    "concave corner radii admit the selected cutter"
                    if status == "pass"
                    else "a claimed internal corner is smaller than the selected cutter radius"
                )
        rows.append(
            Finding(
                "internal_corner_radius", subject, status, values, cite, f"{subject}: {message}."
            )
        )
    return rows
