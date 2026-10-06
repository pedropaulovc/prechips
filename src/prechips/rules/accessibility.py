"""Offset cutter/holder cylinders, or revolved turning tools, never zero-radius ray claims.

Printed DRO checkpoints (coordinates arc/line tables) are checked in the kernel (rule A′): a
checkpoint whose cutter meets the finished part, the op's rough leave, a fixture component or
stock outside a bounded op's box, or removes stock a later setup grips, presses, locates,
rests or supports on, is an error naming the row; an unknown check never passes the op.
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

_CHECKPOINT_KEYS = (
    "checkpoint_count",
    "checkpoint_hits",
    "checkpoint_errors",
    "checkpoint_overshoot_ok",
)


def _checkpoint_error(error):
    if "later_setup" in error:
        return (
            f"{error['row']} removes stock later setup {error['later_setup']}'s "
            f"{error['obstacle']} ({error['contact']}) bears on ({error['area_mm2']} mm^2)"
        )
    return f"{error['row']} meets {error['obstacle']} ({error['volume_mm3']} mm^3)"


def _checkpoints(detail):
    """(checkpoint numbers, certain-hit message or None, unknown reason or None)."""
    if "checkpoint_count" not in detail:
        return {}, None, None
    values = {key: detail.get(key, "unknown") for key in _CHECKPOINT_KEYS}
    errors = values["checkpoint_errors"] if isinstance(values["checkpoint_errors"], list) else []
    hit = None
    if errors:
        listed = "; ".join(_checkpoint_error(error) for error in errors[:3])
        more = f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""
        hit = f"printed DRO checkpoint cutter breaks rule A′: {listed}{more}"
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
        windows = detail.get("window_poses")
        if isinstance(windows, list) and windows:
            values["window_poses"] = windows
            standing = [
                f"standing at its {w.get('end')} Z{w.get('z_mm')} it meets "
                + ", ".join(w.get("meets", []))
                for w in windows
                if w.get("meets")
            ]
            if standing and status == "error":
                message += " (" + "; ".join(standing) + ")"
        engage = detail.get("rest_engagement")
        if isinstance(engage, list) and engage:
            values["rest_engagement"] = engage
            if status == "pass":
                status = "warn"
                message = "; ".join(
                    f"{e.get('rest')} jaws set on the work with the tool at its start "
                    f"Z{e.get('start_z_mm')} meet {', '.join(e.get('meets', []))}: "
                    + (
                        f"set them only once the tool has passed Z{e['engage_z_mm']:.3f}"
                        if number(e.get("engage_z_mm"))
                        else "no clear jaw position before the cut is established"
                    )
                    for e in engage
                )
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
