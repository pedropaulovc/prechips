"""Pure, fact-local mounted-disk inputs shared by host rules and the native job.

Fixture primitives and poses deliberately use the ordinary host transport. A disk's
projection is its body midplane to the selected holder's gauge plane, never OAL minus grip.
Explicitly posed fixture supports can supply the same named calibration faces as clamps.
"""

from __future__ import annotations

import math

from prechips.measurements import cited_fact, length_fact, limits_fact, record_trusted
from prechips.rules.resolution import MANUAL, identity, number, projection_holder, record

UNKNOWN = "unknown"


def _identity(bundle, reference, slot):
    category, key = identity(bundle, reference, slot)
    return f"{category}.{key}" if category and key not in (None, UNKNOWN) else UNKNOWN


def _child(host, item, field, child, suffix=None):
    """Register a nested fact owner without inheriting a parent's evidence."""
    state = host._INPUT_DEBTS.get()
    if state is not None and id(item) in state["items"]:
        _, category, key, prefix = state["items"][id(item)]
        state["items"][id(child)] = (child, category, key, prefix + (suffix or field) + ".")
    return child


def _messages(section, values):
    """Keep dimensional debt keyed to its field and other refusals stably scoped."""
    result = {}
    for index, value in enumerate(values):
        prefix, separator, _ = value.partition(":")
        local = prefix if separator and prefix.startswith(("blade.", "arbor.")) else str(index)
        key = f"{section}.{local}"
        result[key if key not in result else f"{key}.{index}"] = value
    return result


def _rotation(host, item, field, reasons):
    raw = item.get(field, UNKNOWN)
    value = raw.get("value", UNKNOWN) if isinstance(raw, dict) else raw
    trusted, why = record_trusted(raw, require_measured=True)
    if value not in ("cw", "ccw") or not trusted:
        reasons.append(f"{field}: {why}" if value in ("cw", "ccw") else f"{field} is unknown")
        host._record_debt(
            item,
            raw,
            field,
            {"verified": False, "value": value, "measurement_status": UNKNOWN, "reason": why},
        )
        return UNKNOWN
    return value


def _trajectory(value, plane):
    reasons, errors = [], []
    source = record(value)
    result = {"start_mm": source.get("start_mm", UNKNOWN), "moves": source.get("moves", UNKNOWN)}
    start, moves = result["start_mm"], result["moves"]

    def vector(point):
        return (
            isinstance(point, list)
            and len(point) == 3
            and all(number(v) and math.isfinite(v) for v in point)
        )

    if not vector(start) or not isinstance(moves, list) or not moves:
        reasons.append("saw_trajectory needs a numeric setup-mm start and nonempty moves")
    else:
        previous, cuts = start, []
        for index, move in enumerate(moves):
            move = record(move)
            target, mode = move.get("to_mm"), move.get("mode")
            if not vector(target) or mode not in ("cut", "clear"):
                reasons.append(f"trajectory move {index} has unknown coordinates or mode")
                continue
            changed = [axis for axis in range(3) if target[axis] != previous[axis]]
            if len(changed) != 1:
                reasons.append(
                    f"trajectory move {index}: only a finite single-axis straight move is supported"
                )
            if mode == "cut":
                cuts.append(index)
                if changed not in ([0], [1]):
                    reasons.append(
                        f"trajectory move {index}: axial plunges and diagonal cuts are unsupported"
                    )
                if plane.get("axis") != "z" or not number(plane.get("value")):
                    reasons.append("mounted disk needs a numeric setup-Z cut plane")
                elif previous[2] != plane["value"] or target[2] != plane["value"]:
                    errors.append(
                        "cut trajectory Z does not match the cutting-band-midplane cut_plane"
                    )
            previous = target
        if len(cuts) != 1:
            reasons.append("mounted disk supports exactly one straight constant-Z cut move")
    result.update(reasons=reasons, errors=errors)
    return result


def _placed(host, bundle, reference, pose, label, reasons):
    item = host.measurement_item(bundle, "fixtures", reference)
    placed_pose = host._pose(pose)
    if not item:
        reasons.append(f"{label} fixture {reference!r} does not resolve")
    if placed_pose is None:
        reasons.append(f"{label} needs an orthonormal setup-mm pose")
    solids, missing = host._solids(item, reference)
    reasons.extend(missing)
    return {
        "name": reference,
        "pose": placed_pose if placed_pose is not None else UNKNOWN,
        "solids": solids,
    }


def _capture(host, bundle, setup, value):
    source, reasons, errors = record(value), [], []
    result = {
        key: source.get(key, UNKNOWN)
        for key in ("fixture", "pose", "moving_clamp", "moving_clamp_pose", "state")
    }
    if result["state"] == "released":
        errors.append("upper-child capture is released during the mounted-saw cycle")
    elif result["state"] != "clamped":
        reasons.append("upper-child capture clamped state is unknown")
    primary = record(setup.get("hold")).get("fixture")
    if result["fixture"] not in (None, UNKNOWN) and identity(
        bundle, result["fixture"], "workholding"
    ) == identity(bundle, primary, "workholding"):
        errors.append("upper-child capture must be independent of the primary lower-remainder hold")
    result["components"] = [
        {
            **_placed(host, bundle, result["fixture"], result["pose"], "capture", reasons),
            "role": "fixture",
        },
        {
            **_placed(
                host,
                bundle,
                result["moving_clamp"],
                result["moving_clamp_pose"],
                "capture moving clamp",
                reasons,
            ),
            "role": "moving_clamp",
        },
    ]
    if result["fixture"] not in (None, UNKNOWN) and identity(
        bundle, result["fixture"], "fixtures"
    ) == identity(bundle, result["moving_clamp"], "fixtures"):
        errors.append("capture fixture and moving clamp must name independent components")
    result.update(reasons=reasons, errors=errors)
    return result


def _touch_position(ops, touch, kind):
    from prechips.rules.zero_recipe.faces import _boundary

    if kind == "axis" and "after_op" not in touch:
        return 0
    position = _boundary(ops, touch)
    return None if position == UNKNOWN else position


def _zero(host, bundle, setup, op, capture):
    zero, ops = record(setup.get("zero")), setup.get("ops", [])
    reasons, errors, touches, fixtures = [], [], [], []
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))

    def normalized_length(source, field):
        value = source.get(field, UNKNOWN)
        return value * scale if number(value) and scale else UNKNOWN

    pair = (
        _identity(bundle, op.get("tool"), "tools"),
        _identity(bundle, op.get("holder"), "holders"),
    )
    op_position = next(
        (
            i
            for i, candidate in enumerate(ops)
            if candidate is op or candidate.get("op") == op.get("op")
        ),
        None,
    )
    sources = [("axis", record(zero.get("z")))]
    if isinstance(zero.get("tool_touches"), list):
        sources.extend(("tool", record(touch)) for touch in zero["tool_touches"])
    selected, events = UNKNOWN, []
    for order, (kind, source) in enumerate(sources):
        position = _touch_position(ops, source, kind)
        sets_z = bool(source) if kind == "axis" else bool(source.get("z_face"))
        if source.get("method") != "mounted_saw_side":
            if sets_z:
                events.append((position, order, UNKNOWN))
            continue
        touch = {
            "kind": kind,
            "axis": "z",
            "method": source["method"],
            "tool": _identity(bundle, source.get("tool"), "spindle"),
            "holder": _identity(bundle, source.get("holder"), "holders"),
            "tool_reference": source.get("tool", UNKNOWN),
            "holder_reference": source.get("holder", UNKNOWN),
            "face": source.get("face", source.get("z_face", source.get("feature", UNKNOWN))),
            "edge_mm": normalized_length(source, "edge_mm"),
            "paper_mm": normalized_length(source, "paper_mm"),
            "check_jog_mm": normalized_length(source, "check_jog_mm"),
            "mounted_saw": record(source.get("mounted_saw")),
            "position": position if position is not None else UNKNOWN,
            **{key: source[key] for key in ("before_ops", "after_op") if key in source},
        }
        touches.append(touch)
        events.append((position, order, len(touches) - 1))
        if touch["mounted_saw"].get("spindle_state") == "running":
            errors.append("mounted-saw calibration touch requires a stopped spindle")
    # The last Z-setting action wins, including another tool's touch without a cut.
    # Equal-boundary actions follow axis zero, then authored tool_touches order.
    if op_position is not None and not any(position is None for position, _, _ in events):
        current = [event for event in events if event[0] <= op_position]
        if current:
            position, order, selected = max(current, key=lambda event: event[:2])
    if selected != UNKNOWN:
        touch = touches[selected]
        source = sources[order][1]
        kind, position = touch["kind"], touch["position"]
        if pair != (touch["tool"], touch["holder"]):
            selected = UNKNOWN
        elif (
            kind == "tool"
            and isinstance(source.get("before_ops"), list)
            and op.get("op") not in source["before_ops"]
        ):
            selected = UNKNOWN
        intervening = [
            candidate
            for candidate in ops[position:op_position]
            if candidate.get("do") not in MANUAL
        ]
        if any(
            (
                _identity(bundle, candidate.get("tool"), "spindle"),
                _identity(bundle, candidate.get("holder"), "holders"),
            )
            != pair
            for candidate in intervening
        ):
            selected = UNKNOWN
    if selected == UNKNOWN:
        reasons.append("no current mounted_saw_side touch matches the installed tool-holder pair")
    else:
        touch = touches[selected]
        contact = touch["mounted_saw"]
        if contact.get("spindle_state") == "running":
            errors.append("mounted-saw calibration touch requires a stopped spindle")
        elif contact.get("spindle_state") != "stopped":
            reasons.append("mounted-saw calibration spindle state is unknown")
        if contact.get("blade_side") not in ("minus_z", "plus_z"):
            reasons.append("mounted-saw calibration blade side is unknown")
        if not (
            isinstance(contact.get("axis_xy_mm"), list)
            and len(contact["axis_xy_mm"]) == 2
            and all(number(v) for v in contact["axis_xy_mm"])
        ) or not host._vector(contact.get("point_mm")):
            reasons.append(
                "mounted-saw calibration needs numeric axis XY and contact point in setup mm"
            )
        if not number(touch["paper_mm"]):
            reasons.append("mounted-saw calibration paper thickness is unknown")
        elif touch["paper_mm"] < 0:
            errors.append("mounted-saw calibration paper thickness cannot be negative")
        if not number(touch["edge_mm"]):
            reasons.append("mounted-saw calibration contact-plane coordinate is unknown")
        face = touch["face"]
        if not isinstance(face, str) or face in ("", UNKNOWN):
            reasons.append(
                "mounted-saw calibration needs a named contact face, not an edge number alone"
            )
        elif face.startswith("fixture:"):
            target, separator, side = face.removeprefix("fixture:").rpartition(":")
            reference, slash, component = target.rpartition("/")
            if not separator or side not in ("+z", "-z") or not slash or not component:
                errors.append(
                    "mounted-saw fixture face must be "
                    "fixture:<inventory-reference>/<component-id>:+z or :-z"
                )
            else:
                touch["surface"] = {"kind": "fixture", "name": UNKNOWN, "side": side}
                placements = list(capture.get("components", []))
                hold = record(setup.get("hold"))
                for ref, pose in [
                    (hold.get("fixture"), hold.get("pose")),
                    (hold.get("stop_fixture"), hold.get("stop_pose")),
                ]:
                    if ref not in (None, UNKNOWN) and identity(bundle, ref, "fixtures") == identity(
                        bundle, reference, "fixtures"
                    ):
                        placements.append(_placed(host, bundle, ref, pose, "calibration", reasons))
                for clamp in hold.get("clamps", []) if isinstance(hold.get("clamps"), list) else []:
                    clamp = record(clamp)
                    if identity(bundle, clamp.get("ref"), "fixtures") == identity(
                        bundle, reference, "fixtures"
                    ):
                        placements.append(
                            _placed(
                                host,
                                bundle,
                                clamp.get("ref"),
                                clamp.get("pose"),
                                "calibration",
                                reasons,
                            )
                        )
                supports = hold.get("supports")
                for support in supports if isinstance(supports, list) else []:
                    support = record(support)
                    ref = support.get("ref")
                    if (
                        support.get("placement") == "posed"
                        and ref not in (None, UNKNOWN)
                        and identity(bundle, ref, "fixtures")
                        == identity(bundle, reference, "fixtures")
                    ):
                        placements.append(
                            _placed(host, bundle, ref, support.get("pose"), "calibration", reasons)
                        )
                fixtures = [
                    p
                    for p in placements
                    if identity(bundle, p.get("name"), "fixtures")
                    == identity(bundle, reference, "fixtures")
                ]
                if not fixtures:
                    reasons.append(
                        "mounted-saw calibration fixture has no explicit posed placement"
                    )
                matching = [
                    solid["name"]
                    for placement in fixtures
                    for solid in placement["solids"]
                    if solid.get("local") == component and not solid.get("void")
                ]
                if len(matching) == 1:
                    touch["surface"]["name"] = matching[0]
                elif not matching:
                    errors.append("mounted-saw calibration names no solid component in its fixture")
                else:
                    reasons.append("mounted-saw calibration fixture placement is ambiguous")
        else:
            contact_side = "+z" if contact.get("blade_side") == "minus_z" else "-z"
            touch["surface"] = {"kind": "stock", "side": contact_side, "face": face}
    return {
        "touches": touches,
        "selected": selected,
        "fixtures": fixtures,
        "reasons": reasons,
        "errors": errors,
    }


def prepare(bundle, setup, op):
    """Normalize one physical mounted saw without starting or preparing a native job."""
    from prechips import kernel as host

    reasons, errors = [], []
    raw = {}
    tool = host.measurement_item(bundle, "tools", op.get("tool"))
    holder = host.measurement_item(bundle, "holders", op.get("holder"))
    arbor_source = host._nested_item(holder, "mounted_saw_arbor")
    labels = {id(tool): "blade", id(holder): "arbor", id(arbor_source): "arbor"}
    engagement_reasons, engagement_errors = [], []

    def length(item, stem, *, positive=True):
        fact = length_fact(item, stem, require_measured=True)
        host._length_debt(item, stem, True)
        raw[(id(item), stem)] = fact["value"]
        if number(fact["value"]) and positive and fact["value"] <= 0:
            errors.append(f"{stem} must be positive")
        if not fact["verified"]:
            path = ".".join(stem) if isinstance(stem, tuple) else stem + "_mm"
            reasons.append(f"{labels.get(id(item), 'arbor.components')}.{path}: {fact['reason']}")
        return fact["value"] if fact["verified"] else UNKNOWN

    def limits(item, stem):
        fact = limits_fact(item, stem, require_measured=True)
        raw[(id(item), stem)] = fact["value"]
        keys = [key for key in (stem + "_mm", stem + "_in") if key in item]
        value = item.get(keys[0]) if len(keys) == 1 else None
        if not fact["verified"]:
            reasons.append(f"{labels.get(id(item), 'arbor')}.{stem}_mm: {fact['reason']}")
            host._record_debt(item, value, stem, fact)
        if len(keys) == 1:
            pair = value.get("value") if isinstance(value, dict) else value
            if (
                isinstance(pair, list)
                and len(pair) == 2
                and all(number(v) for v in pair)
                and not 0 < pair[0] <= pair[1]
            ):
                errors.append(f"{stem} must be a positive ordered interval")
        return fact["value"] if fact["verified"] else UNKNOWN

    blade = {
        key + "_mm": length(tool, key, positive=key != "kerf_offset")
        for key in ("dia", "root_dia", "thickness", "kerf", "kerf_offset")
    }
    blade["bore_dia_limits_mm"] = limits(tool, "bore_dia_limits")
    blade["flutes"] = tool.get("flutes", UNKNOWN)
    blade["tooth_spacing"] = tool.get("tooth_spacing", UNKNOWN)
    if not isinstance(blade["flutes"], int) or isinstance(blade["flutes"], bool):
        engagement_reasons.append("mounted blade needs one integer flutes count")
    elif blade["flutes"] <= 0:
        engagement_errors.append("mounted blade flutes must be positive")
    if blade["tooth_spacing"] != "uniform":
        engagement_reasons.append("mounted blade tooth_spacing is not known uniform")
    pair, conflict = projection_holder(bundle, tool, op.get("holder"))
    projection = UNKNOWN
    if conflict:
        reasons.append(conflict)
        host._record_debt(
            tool,
            None,
            "projection",
            {
                "verified": False,
                "value": UNKNOWN,
                "measurement_status": UNKNOWN,
                "reason": conflict,
            },
        )
    elif pair is None:
        reasons.append("mounted disk needs a measured projection for this exact tool-holder pair")
        host._length_debt(tool, ("projection", str(op.get("holder", UNKNOWN))), True)
    else:
        projection = length(tool, ("projection", pair))
    arbor = {
        "projection_mm": projection,
        "gauge_len_mm": length(holder, "gauge_len"),
        "pilot_dia_limits_mm": limits(arbor_source, "pilot_dia_limits"),
        "blade_thickness_limits_mm": limits(arbor_source, "blade_thickness_limits"),
        "envelope_state": arbor_source.get("envelope_state", UNKNOWN),
        "retaining_side": arbor_source.get("retaining_side", UNKNOWN),
        "retaining_thread_hand": arbor_source.get("retaining_thread_hand", UNKNOWN),
    }
    clearance_keys = [
        key for key in ("bore_clearance_max_mm", "bore_clearance_max_in") if key in arbor_source
    ]
    clearance_key = clearance_keys[0] if len(clearance_keys) == 1 else "bore_clearance_max_mm"
    clearance = cited_fact(arbor_source, clearance_key, domain=(lambda v: v >= 0, ">= 0"))
    clearance_value = clearance["value"]
    clearance_raw = arbor_source.get(clearance_key, UNKNOWN)
    clearance_raw = (
        clearance_raw.get("value", UNKNOWN) if isinstance(clearance_raw, dict) else clearance_raw
    )
    if number(clearance_raw) and clearance_raw < 0:
        errors.append("arbor bore clearance maximum cannot be negative")
    if number(clearance_value) and clearance_key.endswith("_in"):
        clearance_value *= 25.4
    arbor["bore_clearance_max_mm"] = (
        clearance_value if clearance["verified"] and len(clearance_keys) == 1 else UNKNOWN
    )
    if arbor["bore_clearance_max_mm"] == UNKNOWN:
        reasons.append("bore_clearance_max needs one fact-local cited or measured allowance")
        host._record_debt(
            arbor_source, arbor_source.get(clearance_key), "bore_clearance_max", clearance
        )
    arbor["cutting_rotation"] = _rotation(host, arbor_source, "cutting_rotation", reasons)
    machine = host.measurement_item(bundle, "machines", setup.get("machine"))
    spindle = host._nested_item(machine, "spindle")
    rotation = _rotation(host, spindle, "rotation", reasons)
    machine_rotation = spindle.get("rotation", UNKNOWN)
    machine_rotation = (
        machine_rotation.get("value", UNKNOWN)
        if isinstance(machine_rotation, dict)
        else machine_rotation
    )
    installed_rotation = arbor_source.get("cutting_rotation", UNKNOWN)
    installed_rotation = (
        installed_rotation.get("value", UNKNOWN)
        if isinstance(installed_rotation, dict)
        else installed_rotation
    )
    if (
        installed_rotation in ("cw", "ccw")
        and machine_rotation in ("cw", "ccw")
        and installed_rotation != machine_rotation
    ):
        errors.append(
            "installed saw teeth cutting rotation does not match machine spindle rotation"
        )
    side, hand = arbor["retaining_side"], arbor["retaining_thread_hand"]
    if side not in ("minus_z", "plus_z") or hand not in ("right", "left"):
        reasons.append("arbor retaining side and thread hand are unknown")
    elif machine_rotation in ("cw", "ccw"):
        tightens = (machine_rotation == "cw") == ((side == "minus_z") == (hand == "right"))
        if not tightens:
            errors.append("machine rotation tends to loosen the arbor retaining thread")
    if arbor["envelope_state"] != "complete":
        reasons.append("arbor complete external envelope through spindle nose is not established")
    components, raw_components = [], []
    values = arbor_source.get("components")
    if not isinstance(values, list) or not values:
        reasons.append("arbor envelope components are unknown")
    for index, value in enumerate(values if isinstance(values, list) else []):
        value = _child(
            host,
            arbor_source,
            "components",
            record(value),
            f"components.{record(value).get('id', index)}",
        )
        labels[id(value)] = f"arbor.components.{value.get('id', index)}"
        component = {
            "id": value.get("id", UNKNOWN),
            **{
                key + "_mm": length(value, key, positive=key == "dia")
                for key in ("dia", "z_min", "z_max")
            },
        }
        components.append(component)
        dims = {key: raw[(id(value), key)] for key in ("dia", "z_min", "z_max")}
        raw_components.append(dims)
        if all(number(dims[key]) for key in ("z_min", "z_max")) and dims["z_min"] >= dims["z_max"]:
            errors.append(f"arbor component {component['id']} must have z_min < z_max")
    arbor["components"] = components
    names = [component["id"] for component in components]
    if any(not isinstance(name, str) or name.strip() in ("", UNKNOWN) for name in names) or len(
        names
    ) != len(set(names)):
        errors.append("arbor components need unique known ids")
    dia, root, body, kerf, offset = (
        raw[(id(tool), key)] for key in ("dia", "root_dia", "thickness", "kerf", "kerf_offset")
    )
    bore, pilot, thickness_limits = (
        raw[(id(item), key)]
        for item, key in (
            (tool, "bore_dia_limits"),
            (arbor_source, "pilot_dia_limits"),
            (arbor_source, "blade_thickness_limits"),
        )
    )
    if isinstance(bore, list) and number(root) and number(dia) and not bore[1] < root < dia:
        errors.append("blade needs 0 < bore limits < tooth root diameter < cutting diameter")
    if all(number(v) for v in (body, kerf, offset)) and abs(offset) + body / 2 > kerf / 2:
        errors.append("blade body band is not wholly inside its cutting kerf band")
    if isinstance(bore, list) and isinstance(pilot, list):
        if pilot[1] > bore[0]:
            errors.append("arbor pilot maximum exceeds blade bore minimum")
        if number(clearance_value) and bore[1] - pilot[0] > clearance_value:
            errors.append("blade bore clearance exceeds arbor qualified maximum")
    if (
        isinstance(thickness_limits, list)
        and number(body)
        and not thickness_limits[0] <= body <= thickness_limits[1]
    ):
        errors.append("blade body thickness is outside arbor mounting limits")
    p_raw = raw.get((id(tool), ("projection", pair)), UNKNOWN)
    if (
        number(p_raw)
        and number(body)
        and isinstance(bore, list)
        and number(root)
        and raw_components
    ):
        lo, hi = -p_raw - body / 2, -p_raw + body / 2
        # A pilot or stem ending at a body face is not contact with its flat annulus.
        flanges = [
            c
            for c in raw_components
            if all(number(c[key]) for key in ("dia", "z_min", "z_max"))
            and c["dia"] > bore[1]
            and (abs(c["z_min"] - hi) <= 1e-7 or abs(c["z_max"] - lo) <= 1e-7)
        ]
        lower = [c for c in flanges if abs(c["z_max"] - lo) <= 1e-7]
        upper = [c for c in flanges if abs(c["z_min"] - hi) <= 1e-7]
        if not lower or not upper:
            reasons.append(
                "arbor flange contact with both flat blade-body sides is not established"
            )
        if any(not bore[1] < c["dia"] < root for c in flanges):
            errors.append("arbor flange must overlap the flat body annulus inside the tooth root")
        complete_intervals = all(
            number(component["z_min"]) and number(component["z_max"])
            for component in raw_components
        )
        gauge = raw.get((id(holder), "gauge_len"), UNKNOWN)
        if complete_intervals and number(gauge):
            cursor = lo
            intervals = sorted(
                [
                    (lo, hi),
                    *((component["z_min"], component["z_max"]) for component in raw_components),
                ]
            )
            for low, high in intervals:
                if low > cursor + 1e-7:
                    break
                cursor = max(cursor, high)
            if cursor < gauge - 1e-7:
                errors.append(
                    "declared complete arbor envelope has an axial gap before the spindle nose"
                )
        for component in raw_components:
            if (
                all(number(component[key]) for key in ("dia", "z_min", "z_max"))
                and component["dia"] > bore[0]
                and min(component["z_max"], hi) - max(component["z_min"], lo) > 1e-7
            ):
                errors.append("arbor component intersects the blade flat body instead of its bore")
    spindle_taper, holder_taper = spindle.get("taper"), holder.get("taper")
    interfaces_unverified = any(
        item.get("verify") is True or item.get("verify") == UNKNOWN
        for item in (holder, machine, spindle)
    )
    if interfaces_unverified:
        reasons.append("mounted saw holder/machine spindle interface requires verification")
    elif (
        spindle_taper not in (None, UNKNOWN)
        and holder_taper not in (None, UNKNOWN)
        and spindle_taper != holder_taper
    ):
        errors.append("mounted saw holder spindle interface does not match the selected machine")
    elif spindle_taper in (None, UNKNOWN) or holder_taper in (None, UNKNOWN):
        reasons.append("mounted saw holder/machine spindle interface is unknown")
    assembly_reasons, assembly_errors = list(dict.fromkeys(reasons)), list(dict.fromkeys(errors))
    reasons.extend(engagement_reasons)
    errors.extend(engagement_errors)
    plane = host.saw_plane(op.get("cut_plane"), bundle.features.get("units", UNKNOWN))
    trajectory = _trajectory(op.get("saw_trajectory"), plane)
    capture = _capture(host, bundle, setup, op.get("saw_capture"))
    zero = _zero(host, bundle, setup, op, capture)
    for section in (trajectory, capture, zero):
        reasons.extend(section["reasons"])
        errors.extend(section["errors"])
    direction = op.get("direction", UNKNOWN)
    if direction != "conventional":
        (reasons if direction in (None, UNKNOWN) else errors).append(
            "mounted saw requires a geometrically conventional feed direction"
        )
    reasons, errors = list(dict.fromkeys(reasons)), list(dict.fromkeys(errors))
    return {
        "model": "finite_disk_v1",
        "status": "error" if errors else UNKNOWN if reasons else "pass",
        "tool": _identity(bundle, op.get("tool"), "tools"),
        "holder": _identity(bundle, op.get("holder"), "holders"),
        "diagnostics": {"blade_diameter_mm": dia if number(dia) and dia <= 0 else UNKNOWN},
        "blade": blade,
        "arbor": arbor,
        "trajectory": trajectory,
        "spindle_rotation": rotation,
        "direction": direction,
        "capture": capture,
        "zero": zero,
        "assembly_reasons": assembly_reasons,
        "assembly_errors": assembly_errors,
        "reasons": {
            **_messages("assembly", assembly_reasons),
            **_messages("engagement", engagement_reasons),
            **{
                key: value
                for name, section in (
                    ("trajectory", trajectory),
                    ("capture", capture),
                    ("zero", zero),
                )
                for key, value in _messages(name, section["reasons"]).items()
            },
            **(
                {"direction": reasons[-1]}
                if direction != "conventional" and direction in (None, UNKNOWN)
                else {}
            ),
        },
        "errors": {
            **_messages("assembly", assembly_errors),
            **_messages("engagement", engagement_errors),
            **{
                key: value
                for name, section in (
                    ("trajectory", trajectory),
                    ("capture", capture),
                    ("zero", zero),
                )
                for key, value in _messages(name, section["errors"]).items()
            },
            **(
                {"direction": errors[-1]}
                if direction != "conventional" and direction not in (None, UNKNOWN)
                else {}
            ),
        },
    }
