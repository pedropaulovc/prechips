"""Offset cutter/holder cylinders, or revolved turning tools, never zero-radius ray claims.

Printed DRO checkpoints (coordinates arc/line tables) are checked in the kernel (rule A′): a
checkpoint whose cutter meets the finished part, the op's rough leave, a fixture component or
stock outside a bounded op's box, or removes stock a later setup grips, presses, locates,
rests or supports on, is an error naming the row; an unknown check never passes the op.

A bounded op is judged only on the claimed-face samples its cutter reaches without meeting
stock outside its stock_removal_bounds; the rest is debt a later op claiming that face must
discharge.
"""

from dataclasses import replace

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    TURNING,
    TURNING_HOLDER_KEYS,
    TURNING_TOOL_KEYS,
    blade_keys,
    cutting_action,
    fact_reason,
    op_claims,
    op_contexts,
    with_measurement_debts,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    SAW_OPS,
    claim_refs,
    identity,
    known_refs,
    number,
    operations,
    record,
)

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


def _takes(op):
    """Whether a later ``op`` can take a carried face: True when it cuts (rough cuts
    included) or files to the line, False for a saw, a coating or other non-cutting work,
    None when its action is unknown."""
    if op.get("do") in SAW_OPS | {"coating"}:
        return False
    if op.get("do") in HAND_FINISH:
        return True
    return cutting_action(op)


def _carried(bundle, facts, op, unreached):
    """(numbers, verdict, why) for a bounded op's claimed-face samples whose cutter would
    meet its stock outside its stock_removal_bounds (kernel ``bounds_unreached``), or None.

    The kernel judges the op only where its cutter may stand; the rest of each such face
    stays under the stock as carried debt. A later op that cuts or files to the line
    (:func:`_takes`; never a saw) whose kernel claim holds the face discharges it, and is
    judged on it in turn. A later op naming the face, or one whose refs are unknown, with
    an unknown claim, or an op of unknown action claiming it, leaves it unknown. With
    neither, no op makes that part of the face: an error.
    """
    if not isinstance(unreached, dict):
        return None
    count, indices = unreached.get("sample_count"), unreached.get("indices")
    numbers = {"sample_count": count, "faces": [], "carried_to": {}}
    if not (
        number(count)
        and count > 0
        and isinstance(indices, list)
        and indices
        and all(isinstance(index, int) and not isinstance(index, bool) for index in indices)
    ):
        return numbers, "unknown", "its claimed-face samples beyond its box are unresolved"
    refs = {
        face.get("index"): face.get("ref")
        for face in facts.get("faces") or []
        if isinstance(face, dict) and isinstance(face.get("ref"), str)
    }
    mapping = record(facts.get("mapping"))
    ops = operations(bundle)
    position = next(k for k, (_, other) in enumerate(ops) if other is op)
    later = [
        (f"{other_setup['id']}:{other['op']}", other_setup, other, takes)
        for other_setup, other in ops[position + 1 :]
        if (takes := _takes(other)) is not False
    ]
    unresolved, uncovered = [], []
    for index in sorted(indices):
        ref = refs.get(index, f"face index {index}")
        numbers["faces"].append(ref)
        takers, open_claim = [], False
        for subject, other_setup, other, takes in later:
            claims = op_claims(bundle, facts, other_setup, other)[0]
            if claims is None:
                named = claim_refs(bundle, other)
                open_claim = open_claim or not known_refs(named)
                open_claim = open_claim or any(mapping.get(name) == index for name in named)
            elif index in claims:
                if takes:
                    takers.append(subject)
                else:
                    open_claim = True
        if takers:
            numbers["carried_to"][ref] = takers
        else:
            (unresolved if open_claim else uncovered).append(ref)
    beyond = f"{count} claimed-face sample(s) need its cutter beyond its stock_removal_bounds"
    if uncovered:
        return numbers, "error", f"{beyond} and no later op claims {', '.join(uncovered)}"
    if unresolved:
        faces = ", ".join(unresolved)
        return numbers, "unknown", f"{beyond} and whether a later op claims {faces} is unknown"
    takers = sorted({subject for named in numbers["carried_to"].values() for subject in named})
    return numbers, "pass", f"{beyond}, carried to {', '.join(takers)}"


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
    for setup, op, facts, detail, inputs, cite, blocked in op_contexts(
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
        # they are unknown): the traveler's jaw distance, whatever the op's own verdict. A
        # kernel that never posed the tool reports none: that is unknown, never absent.
        keys = ("tool_z_mm", "nose_z_mm")
        extent = {key: detail.get(key, "unknown") for key in keys} if turned else {}
        # A bounded op's carried debt needs only the kernel's unreached samples and the
        # later ops' claims, never the dimensions or context that left this op blocked.
        carried = _carried(bundle, facts, op, detail.get("bounds_unreached"))
        if blocked:
            occluded = any(number(value) and value > 0 for value in certain.values())
            uncovered = carried is not None and carried[1] == "error"
            unreached = {} if carried is None else {"bounds_unreached": carried[0]}
            if blocked.status == "unknown" and (occluded or uncovered or checkpoint_hit):
                causes = []
                if occluded:
                    causes.append(
                        "selected cutter or holder is certainly occluded by part/fixture material"
                    )
                if uncovered:
                    causes.append(carried[2])
                if checkpoint_hit:
                    causes.append(checkpoint_hit)
                rows.append(
                    Finding(
                        "accessibility",
                        blocked.subject,
                        "error",
                        {**certain, **unreached, **checkpoints, **extent},
                        cite,
                        f"{blocked.subject}: {'; '.join(causes)}.",
                    )
                )
            else:
                rows.append(replace(blocked, numbers={**blocked.numbers, **unreached, **extent}))
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
        if carried is not None:
            values["bounds_unreached"], verdict, why = carried
            if verdict == "error":
                message = f"{message}; {why}" if status == "error" else why
                status = "error"
            elif verdict == "unknown" and status != "error":
                message = why if status == "pass" else f"{message}; {why}"
                status = "unknown"
            elif status == "pass":
                message = f"{message}; {why}"
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
            with_measurement_debts(
                Finding("accessibility", subject, status, values, cite, f"{subject}: {message}."),
                inputs["measurement_debts"],
            )
        )
    return rows
