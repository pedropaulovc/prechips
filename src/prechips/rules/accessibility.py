"""Offset cutter/holder cylinders, or revolved turning tools, never zero-radius ray claims.

Printed DRO checkpoints (coordinates arc/line tables) are checked in the kernel (rule A′): a
checkpoint whose cutter meets the finished part, the op's rough leave, a fixture component or
stock outside a bounded op's box, or removes stock a later setup grips, presses, locates,
rests or supports on, is an error naming the row; an unknown check never passes the op.
"""

from dataclasses import replace

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    TURNING,
    TURNING_HOLDER_KEYS,
    TURNING_TOOL_KEYS,
    blade_keys,
    fact_reason,
    op_contexts,
)
from prechips.rules.resolution import identity, number

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


def _engagement(bundle, setup, op, entry, feed_z, scale):
    """(status, declared Z, why) for one kernel ``rest_engagement`` entry: a follow rest
    whose jaws, set with the tool at the op's start, would meet a fixture component. The
    plan's ``hold.supports[].engage_at_z_mm`` (the cut Z the tool passes before the jaws
    go on) passes once it is at or past the computed clear Z along the feed and within the
    op's window; before it is an error; undeclared or uncomputed stays unknown. All three
    are millimetres: the op's plan-unit ``z_to`` is scaled by ``scale`` (mm per unit)."""
    rest, op_number = entry.get("rest"), op.get("op")
    supports = (setup.get("hold") or {}).get("supports")
    items = supports if isinstance(supports, list) else []
    declared = next(
        (
            item.get("engage_at_z_mm", "unknown")
            for item in items
            if isinstance(item, dict)
            and identity(bundle, item.get("ref"), "fixtures") == identity(bundle, rest, "fixtures")
            and (not isinstance(item.get("ops"), list) or op_number in item["ops"])
        ),
        "unknown",
    )
    clear, met = entry.get("engage_z_mm"), ", ".join(entry.get("meets", []))
    start = f"{rest} jaws set with the tool at its start Z{entry.get('start_z_mm'):g} meet {met}"
    if not number(declared):
        why = f"{start}: declare hold.supports[{rest}].engage_at_z_mm, the Z the tool passes "
        why += f"before the jaws go on (clear from Z{clear:.3f})" if number(clear) else "first"
        return "unknown", "unknown", why
    if not number(clear) or feed_z not in (-1, 1):
        return "unknown", declared, f"{start}: no clear jaw position was computed to check"
    end = op.get("z_to")
    if number(end) and not number(scale):
        return "unknown", declared, f"{start}: the op's end is in unknown plan units"
    if (declared - clear) * feed_z < -1e-9:
        return (
            "error",
            declared,
            (f"{start}: set at Z{declared:g}, before Z{clear:.3f} where they clear it"),
        )
    if number(end) and (declared - end * scale) * feed_z > 1e-9:
        return (
            "error",
            declared,
            f"{start}: set at Z{declared:g}, after the op ends at Z{end * scale:g} mm",
        )
    return "pass", declared, None


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
        # The whole turning tool's axial extent and its nose's over the same poses (or why
        # they are unknown): the traveler's jaw distance, whatever the op's own verdict.
        keys = ("tool_z_mm", "nose_z_mm")
        extent = {key: detail[key] for key in keys if turned and key in detail}
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
                        {**certain, **checkpoints, **extent},
                        cite,
                        f"{blocked.subject}: {message}.",
                    )
                )
            else:
                rows.append(replace(blocked, numbers={**blocked.numbers, **extent}))
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
        values.update(extent)
        engage = detail.get("rest_engagement")
        if isinstance(engage, list) and engage:
            scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
            feed = values.get("feed_z")
            judged = [_engagement(bundle, setup, op, e, feed, scale) for e in engage]
            values["rest_engagement"] = [
                e | {"declared_z_mm": z} for e, (_, z, _) in zip(engage, judged, strict=True)
            ]
            rank = {"pass": 0, "unknown": 1, "error": 2}
            worst = max((verdict for verdict, _, _ in judged), key=rank.get)
            notes = [why for verdict, _, why in judged if verdict != "pass"]
            if worst == "error" or (status == "pass" and worst == "unknown"):
                message = (
                    "; ".join(notes) if status == "pass" else f"{message}; " + "; ".join(notes)
                )
                status = worst
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
