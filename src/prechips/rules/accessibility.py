"""Offset cutter/holder cylinder intersections, never zero-radius ray claims."""

from prechips.findings import Finding
from prechips.rules.geometry_common import fact_reason, op_contexts
from prechips.rules.resolution import number


def evaluate(bundle):
    rows = []
    required = (
        "radius_mm",
        "flute_len_mm",
        "oal_mm",
        "projection_mm",
        "holder_radius_mm",
        "holder_gauge_len_mm",
    )
    for setup, op, _, detail, inputs, cite, blocked in op_contexts(
        bundle, "accessibility", required, fixture=True
    ):
        if blocked:
            rows.append(blocked)
            continue
        subject = f"{setup['id']}:{op['op']}"
        values = {
            key: detail.get(key, "unknown") for key in ("sample_count", "tool_hits", "holder_hits")
        }
        values.update({key: inputs[key] for key in required})
        known = (
            all(
                number(values[key]) and values[key] >= 0
                for key in ("sample_count", "tool_hits", "holder_hits")
            )
            and values["sample_count"] > 0
        )
        status = "unknown"
        message = fact_reason(
            detail,
            ("sample_count", "tool_hits", "holder_hits"),
            "offset-cylinder sampling is unresolved",
        )
        if known:
            status = "error" if values["tool_hits"] > 0 or values["holder_hits"] > 0 else "pass"
            message = (
                "selected cutter or holder is occluded by part/fixture material"
                if status == "error"
                else "sampled claimed faces clear the selected cutter and holder cylinders"
            )
        minimum = detail.get("min_hits", {})
        if isinstance(minimum, dict):
            for key in ("tool", "holder"):
                if key in minimum:
                    values["certain_" + key + "_hits"] = minimum[key]
        if any(
            number(values.get(key)) and values[key] > 0
            for key in ("tool_hits", "holder_hits", "certain_tool_hits", "certain_holder_hits")
        ):
            status, message = (
                "error",
                "selected cutter or holder is certainly occluded by part/fixture material",
            )
        rows.append(
            Finding("accessibility", subject, status, values, cite, f"{subject}: {message}.")
        )
    return rows
