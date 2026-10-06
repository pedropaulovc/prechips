"""Concave claimed-face edges perpendicular to the setup tool axis."""

from prechips.findings import Finding
from prechips.rules.geometry_common import fact_reason, op_contexts
from prechips.rules.resolution import UNKNOWN, _citations, number, record, same_length

# STEP exports round radii to 5–6 significant digits; below this a corner is CAD-sharp.
CAD_SHARP_MM = 0.005


def corner_allowance_mm(bundle, feature_name):
    """The feature's declared ``corner_radius_max_design`` in mm, never an edge-break default."""
    feature = record(record(bundle.features.get("features")).get(feature_name))
    value = feature.get("corner_radius_max_design", UNKNOWN)
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    if not number(value) or value < 0 or scale is None:
        return UNKNOWN
    return value * scale


def admits(corner_mm, tool_mm, allowance_mm):
    """A modelled corner admits a nose at least as small; a CAD-sharp one up to the allowance."""
    if corner_mm >= tool_mm - CAD_SHARP_MM:
        return True
    return (
        corner_mm < CAD_SHARP_MM
        and number(allowance_mm)
        and (tool_mm <= allowance_mm or same_length(tool_mm, allowance_mm))
    )


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
                name = op.get("feature", UNKNOWN)
                allowance = corner_allowance_mm(bundle, name)
                sharp = sum(value < CAD_SHARP_MM for value in radii)
                values.update(
                    minimum_corner_radius_mm=min(radii),
                    cad_sharp_corners=sharp,
                    corner_radius_max_design_mm=allowance,
                )
                if sharp:
                    feature = record(bundle.features["features"].get(name))
                    cite = [
                        *cite,
                        f"features.features.{name}.corner_radius_max_design: drawing allowance "
                        f"for CAD-sharp (< {CAD_SHARP_MM} mm) concave corners",
                        *_citations(feature.get("cite"), "corner_radius_max_design"),
                    ]
                status = "pass" if all(admits(r, radius, allowance) for r in radii) else "error"
                message = (
                    "concave corner radii admit the selected cutter"
                    if status == "pass"
                    else "a claimed internal corner is smaller than the selected cutter radius"
                    + (
                        " and the feature declares no corner_radius_max_design admitting it"
                        if sharp and not number(allowance)
                        else ""
                    )
                )
        rows.append(
            Finding(
                "internal_corner_radius", subject, status, values, cite, f"{subject}: {message}."
            )
        )
    return rows
