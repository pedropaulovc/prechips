"""Offset cutter/holder cylinders, or revolved turning tools, never zero-radius ray claims.

Printed DRO checkpoints (coordinates arc/line tables) are checked in the kernel against the
stock model: a checkpoint whose cutter meets retained stock, the finished part or a fixture
component is an error naming the row; an unknown check never passes the op.
"""

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    TURNING,
    TURNING_HOLDER_KEYS,
    TURNING_TOOL_KEYS,
    blade_keys,
    fact_reason,
    op_contexts,
)
from prechips.rules.resolution import number

_CHECKPOINT_KEYS = ("checkpoint_count", "checkpoint_hits", "checkpoint_errors")


def _checkpoints(detail):
    """(checkpoint numbers, certain-hit message or None, unknown reason or None)."""
    if "checkpoint_count" not in detail:
        return {}, None, None
    values = {key: detail.get(key, "unknown") for key in _CHECKPOINT_KEYS}
    errors = values["checkpoint_errors"] if isinstance(values["checkpoint_errors"], list) else []
    hit = None
    if errors:
        listed = "; ".join(
            f"{error['row']} meets {error['obstacle']} ({error['volume_mm3']} mm^3)"
            for error in errors[:3]
        )
        more = f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""
        hit = f"printed DRO checkpoint cutter meets material the stock model keeps: {listed}{more}"
    unknown = None
    if not number(values["checkpoint_hits"]):
        unknown = "printed DRO checkpoints unproven: " + detail.get(
            "checkpoint_reason", "checkpoint check is unresolved"
        )
    return values, hit, unknown


def evaluate(bundle):
    rows = []
    required = (
        "radius_mm",
        "flute_len_mm",
        "projection_mm",
        "holder_radius_mm",
        "holder_gauge_len_mm",
    )
    turning = TURNING_TOOL_KEYS + TURNING_HOLDER_KEYS
    for setup, op, _, detail, inputs, cite, blocked in op_contexts(
        bundle, "accessibility", required, fixture=True, turning=turning
    ):
        turned = inputs.get("approach") == TURNING
        minimum = detail.get("min_hits", {})
        certain = {
            "certain_" + key + "_hits": minimum[key]
            for key in ("tool", "holder")
            if isinstance(minimum, dict) and key in minimum
        }
        checkpoints, checkpoint_hit, checkpoint_unknown = _checkpoints(detail)
        if blocked:
            occluded = any(number(value) and value > 0 for value in certain.values())
            if blocked.status == "unknown" and (occluded or checkpoint_hit):
                message = (
                    "selected cutter or holder is certainly occluded by part/fixture material"
                    if occluded
                    else checkpoint_hit
                )
                if occluded and checkpoint_hit:
                    message += "; " + checkpoint_hit
                rows.append(
                    Finding(
                        "accessibility",
                        blocked.subject,
                        "error",
                        {**certain, **checkpoints},
                        cite,
                        f"{blocked.subject}: {message}.",
                    )
                )
            else:
                rows.append(blocked)
            continue
        subject = f"{setup['id']}:{op['op']}"
        values = {
            key: detail.get(key, "unknown") for key in ("sample_count", "tool_hits", "holder_hits")
        }
        values.update(
            {key: inputs[key] for key in ((*turning, *blade_keys(inputs)) if turned else required)}
        )
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
            "revolved turning-tool sampling is unresolved"
            if turned
            else "offset-cylinder sampling is unresolved",
        )
        if known:
            status = "error" if values["tool_hits"] > 0 or values["holder_hits"] > 0 else "pass"
            message = (
                "selected cutter or holder is occluded by part/fixture material"
                if status == "error"
                else "sampled claimed faces clear the selected insert, shank and toolpost body"
                if turned
                else "sampled claimed faces clear the selected cutter and holder cylinders"
            )
        values.update(certain)
        if any(
            number(values.get(key)) and values[key] > 0
            for key in ("tool_hits", "holder_hits", "certain_tool_hits", "certain_holder_hits")
        ):
            status, message = (
                "error",
                "selected cutter or holder is certainly occluded by part/fixture material",
            )
        values.update(checkpoints)
        if checkpoint_hit:
            message = checkpoint_hit if status != "error" else f"{message}; {checkpoint_hit}"
            status = "error"
        elif checkpoint_unknown and status != "error":
            message = checkpoint_unknown if status == "pass" else f"{message}; {checkpoint_unknown}"
            status = "unknown"
        rows.append(
            Finding("accessibility", subject, status, values, cite, f"{subject}: {message}.")
        )
    return rows
