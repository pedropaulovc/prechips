"""Causal hole/thread preparation on the material each operation actually receives.

A typed spot witness names one real earlier stock-preparation cut, never an invented
duplicate on a finished hole. Contour/form starts must still be deterministic faces.
"""

import math

from ..findings import Finding
from ..material_routes import setup_lineage
from ..measurements import angle_fact, length_debt
from ..process_features import process_of
from ..thread_specs import match, selected_class_status
from .resolution import (
    TAP_OPS,
    UNKNOWN,
    length_mm,
    number,
    op_feature,
    operation_material_status,
    operation_members,
    operations,
    record,
    resolve,
    same_length,
    select,
    setup_frame,
    thread_class_acceptance,
    uncertain,
)


def _forms(op):
    """Whether an op prints positions measured from its ``z_from`` (a table or a form)."""
    action = str(op.get("do", ""))
    return "contour" in op or action.startswith(("form", "profile"))


def _z(value):
    return f"{value:g}" if number(value) else "an unknown Z"


def _banded_starts(bundle):
    """({feature: [error clause]}, {feature: [unknown clause]}) for contour/form ops whose
    ``z_from`` is the face an earlier op in the setup leaves only within its ``to_z_band``
    (the last op leaving that Z decides). A band with an unknown end still makes its own
    ``to_z`` a banded face; whether it holds another start is then unknown."""
    errors, unknowns = {}, {}
    for setup in bundle.plan["setups"]:
        ops = setup["ops"]
        for index, op in enumerate(ops):
            start = op.get("z_from")
            if not _forms(op) or not number(start):
                continue
            maybe = []  # later ops whose partly unknown band may hold the start
            for earlier in reversed(ops[:index]):
                to_z, band = earlier.get("to_z"), earlier.get("to_z_band")
                banded = isinstance(band, list) and len(band) == 2
                known = banded and all(number(v) for v in band)
                if not number(to_z):
                    continue
                same = same_length(to_z, start)
                if not same and not (banded and (not known or min(band) <= start <= max(band))):
                    continue
                selected = operation_members(bundle, setup, op)
                prior = operation_members(bundle, setup, earlier)
                if selected and prior is not None and not set(selected) <= set(prior):
                    continue
                if selected is None or prior is None:
                    maybe.append(
                        f"{setup['id']} op {earlier['op']} start-face member is unresolved"
                    )
                    continue
                if not banded:
                    break
                leader = (
                    f"{setup['id']} op {op['op']} starts at Z {start:g}, which op {earlier['op']}"
                )
                lo, hi = sorted(band) if known else band
                if same or known:
                    # Certain whatever the later partly unknown bands hold: if one holds
                    # the start it is banded there, else this band leaves it.
                    errors.setdefault(op_feature(op), []).append(
                        f"{leader} leaves anywhere in {_z(lo)} to {_z(hi)}; an op must leave "
                        "that face at a deterministic to_z first"
                    )
                    maybe = []
                    break
                # Unknown until known not to hold it: keep scanning the earlier producers.
                maybe.append(f"{leader} leaves anywhere in {_z(lo)} to {_z(hi)}, which may hold it")
            if maybe:
                unknowns.setdefault(op_feature(op), []).extend(maybe)
    return errors, unknowns


def _label(setup, op):
    return f"{setup['id']}:{op['op']}"


def _material(bundle, setup, producer, name, *, op=None, producer_op=None):
    """Retained-material proof; missing routing is debt, never a different blank."""
    status = operation_material_status(
        bundle, setup, producer, name, op=op, producer_op=producer_op
    )
    if setup["id"] == producer["id"]:
        return status
    lineage = setup_lineage(bundle.plan, setup["id"])
    routed = all(
        other.get("stock_in") not in (None, UNKNOWN)
        for other in bundle.plan["setups"]
        if other["id"] in lineage
    )
    if not routed and (status is not False or producer["id"] not in lineage):
        return None
    return status


def _geometry(bundle, name):
    """Entry and directed axis in the model frame; missing transforms remain debt."""
    from .coordinates import frame_axes, located_by, model_point

    feature = record(bundle.feature_definitions.get(name))
    locator, frame_name, _ = located_by(bundle.feature_definitions, name, feature)
    at = locator.get("at")
    axis = feature.get("axis", locator.get("axis"))
    at_frame = locator.get("frame", frame_name)
    axis_frame = feature.get("frame", "model") if "axis" in feature else at_frame
    frames = record(bundle.features.get("frames"))

    def vector(value):
        return isinstance(value, list) and len(value) == 3 and all(map(number, value))

    point = at if vector(at) else None
    if point is not None and at_frame != "model":
        point = model_point(point, frames.get(at_frame))
        if not vector(point):
            point = None
    direction = axis if vector(axis) else None
    if direction is not None and axis_frame != "model":
        basis = frame_axes(record(frames.get(axis_frame)))
        direction = (
            [sum(axis[j] * basis[j][i] for j in range(3)) for i in range(3)]
            if all(vector(row) for row in basis)
            else None
        )
    norm = math.sqrt(sum(v * v for v in direction)) if direction is not None else 0
    return point, [v / norm for v in direction] if norm else None


def _spot_witness(bundle, setup, op, target, route, positions, *, preparation=None):
    """Resolve exactly the offered real preparation, retaining every proof boundary."""
    offered = op if preparation is None else preparation
    reference = record(offered.get("prerequisites")).get("spot", UNKNOWN)
    errors, unknown = [], []
    proof = {"operation": _label(setup, op), "spot": reference}
    if reference == UNKNOWN:
        return [], ["the spot prerequisite is unknown"], proof
    sid, separator, ordinal = str(reference).rpartition(":")
    candidates = (
        [(other, cut) for other, cut in route if other["id"] == sid and str(cut["op"]) == ordinal]
        if separator
        else []
    )
    if len(candidates) != 1:
        return ["spot prerequisite does not resolve to exactly one real setup:op"], [], proof
    other, cut = candidates[0]
    if positions[id(cut)] >= positions[id(op)]:
        errors.append("spot prerequisite is not earlier than the operation it prepares")
    source = op_feature(cut)
    definition = record(bundle.feature_definitions.get(source))
    process = process_of(definition)
    kind = record(process).get("kind", UNKNOWN)
    action = cut.get("do", UNKNOWN)
    proof.update(source_feature=source, source_kind=kind, action=action)
    if action == UNKNOWN:
        unknown.append("the prerequisite action is unknown")
    elif action == "center_drill":
        if kind not in {"centre_hole", UNKNOWN}:
            errors.append("center_drill spot prerequisite does not cut a centre")
    elif action != "spot":
        errors.append("spot prerequisite is not a spot or a centre-only center_drill")
    if process is None:
        if definition.get("kind", UNKNOWN) == UNKNOWN:
            unknown.append("the source preparation feature kind is unknown")
        else:
            errors.append("spot prerequisite does not cut a plan process feature")
    elif kind == UNKNOWN:
        unknown.append("the source process feature kind is unknown")
    elif kind not in {"centre_hole", "tooling_hole"}:
        errors.append("spot prerequisite does not prepare a centre or tooling hole")
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    source_at, source_axis = _geometry(bundle, source)
    target_at, target_axis = _geometry(bundle, target)
    if source_at is None or target_at is None or scale is None:
        unknown.append("the preparation and target entry locations are unresolved")
    elif not all(
        same_length(a * scale, b * scale) for a, b in zip(source_at, target_at, strict=True)
    ):
        errors.append("spot prerequisite and target hole have different entry locations")
    if source_axis is None or target_axis is None:
        unknown.append("the preparation or target directed axis is unresolved")
    elif sum(a * b for a, b in zip(source_axis, target_axis, strict=True)) < 1 - 1e-9:
        errors.append("spot prerequisite and target hole have different directed axes")
    for name in (source, target):
        material = _material(bundle, setup, other, name, op=op, producer_op=cut)
        if material is False:
            errors.append(f"spot prerequisite does not belong to the target material ({name})")
        elif material is None:
            unknown.append(f"spot prerequisite retained-material survival is unknown ({name})")
    if kind == "centre_hole" and action in {"spot", "center_drill"}:
        from .tip_endpoints import centre_check

        status, reasons = centre_check(bundle, other, cut)
        proof["preparation"] = status
        if status == "error":
            errors.extend(f"spot prerequisite centre: {reason}" for reason in reasons)
        elif status != "pass":
            unknown.extend(f"spot prerequisite centre: {reason}" for reason in reasons)
    elif kind == "tooling_hole" and action == "spot":
        from .tip_endpoints import (
            _centre_mouth,
            drill_point_mm,
            hole_depth_mm,
            stock_states,
        )

        tool = record(resolve(bundle, "tools", cut.get("tool")))
        depth = hole_depth_mm(cut, definition, bundle.features.get("units"))
        angle = angle_fact(tool, "point_angle", require_measured=False)
        point = drill_point_mm(
            length_mm(tool, "dia"), angle["value"] if angle["verified"] else UNKNOWN
        )
        before = next(
            before for current, before, _ in stock_states(bundle, other) if current is cut
        )
        bad, debt, _ = _centre_mouth(
            bundle,
            other,
            definition,
            before["entry_z"].get(source, before["top_z"]),
        )
        errors.extend(f"prerequisite spot: {reason}" for reason in bad)
        unknown.extend(f"prerequisite spot: {reason}" for reason in debt)
        if not tool or uncertain(tool) or not number(point):
            unknown.append("the prerequisite spot tool or its actual point geometry is unresolved")
        if number(depth) and depth <= 0:
            errors.append("the prerequisite spot does not cut a positive depth")
        elif not number(depth):
            unknown.append("the prerequisite spot depth is unresolved")
    return errors, unknown, proof


def _earlier(bundle, setup, op, target, action, route, positions):
    """Last material-compatible causal producer, with an uncertain producer kept uncertain."""
    for other, cut in reversed(route[: positions[id(op)]]):
        if op_feature(cut) not in (target, UNKNOWN) or cut.get("do") not in {action, UNKNOWN}:
            continue
        material = _material(bundle, setup, other, target, op=op, producer_op=cut)
        if material is not False:
            certain = cut.get("do") == action and op_feature(cut) == target
            return other, cut, material if certain else None
    return None, None, False


def _drill_preparation(bundle, setup, op, target, route, positions, prepared):
    """A drilled pilot carries its proven start into a later same-material enlargement.

    Keep the original real source, not a synthetic spot on the finished hole. An
    explicit prerequisite is always authoritative; inherited proof rechecks that
    source against the receiver as well as the intervening drill's material.
    """
    if "prerequisites" in op:
        errors, unknown, proof = _spot_witness(bundle, setup, op, target, route, positions)
        return errors, unknown, (setup, op), proof
    spot_setup, spot, material = _earlier(bundle, setup, op, target, "spot", route, positions)
    if material is True:
        return [], [], (spot_setup, spot), None
    for earlier_setup, earlier in reversed(route[: positions[id(op)]]):
        if op_feature(earlier) != target or earlier.get("do") != "drill":
            continue
        carried = _material(bundle, setup, earlier_setup, target, op=op, producer_op=earlier)
        if carried is False:
            continue
        bad, debt, source, _ = prepared[id(earlier)]
        errors, unknown, proof = list(bad), list(debt), None
        if carried is None:
            unknown.append(
                f"{_label(setup, op)} prior drill material is unresolved "
                f"({_label(earlier_setup, earlier)})"
            )
        if source is not None:
            source_setup, source_op = source
            if source_op.get("do") == "drill" and "prerequisites" in source_op:
                bad, debt, proof = _spot_witness(
                    bundle,
                    setup,
                    op,
                    target,
                    route,
                    positions,
                    preparation=source_op,
                )
                proof["inherited_from"] = _label(earlier_setup, earlier)
                errors.extend(bad)
                unknown.extend(debt)
            else:
                survives = _material(
                    bundle, setup, source_setup, target, op=op, producer_op=source_op
                )
                if survives is False:
                    errors.append(f"{_label(setup, op)} initial spot is on different material")
                elif survives is None:
                    unknown.append(f"{_label(setup, op)} initial spot material is unresolved")
        return errors, unknown, source, proof
    if material is None:
        return (
            [],
            [f"{_label(setup, op)} prior spot material is unresolved"],
            (spot_setup, spot),
            None,
        )
    return (
        [f"{_label(setup, op)} has no earlier spot operation on its material"],
        [],
        None,
        None,
    )


def _turned_blank(bundle, setup, op, name, route, positions):
    """A same-feature turn must leave the male diameter and its whole axial shoulder."""
    from .coordinates import frame_point

    errors, unknown, candidates = [], [], []
    for other, cut in route[: positions[id(op)]]:
        if op_feature(cut) == name and cut.get("do") in {"rough_turn", "finish_turn", "turn"}:
            candidates.append(
                (other, cut, _material(bundle, setup, other, name, op=op, producer_op=cut))
            )
    if not candidates:
        return [], ["no earlier turned male blank/shoulder preparation is established"], UNKNOWN
    eligible = [candidate for candidate in candidates if candidate[2] is not False]
    if not eligible:
        return ["turned male blank preparation is on different material"], [], UNKNOWN
    other, cut, material = eligible[-1]
    if material is None:
        return [], ["turned male blank retained-material survival is unknown"], _label(other, cut)
    feature = bundle.feature_definitions[name]
    scale = {"mm": 1.0, "in": 25.4}.get(bundle.features.get("units"))
    diameter = cut.get("to_dia")
    band = feature.get("dia")
    nominal = feature.get("nominal_dia", feature.get("dia_nominal"))
    if scale is None or not number(diameter):
        unknown.append("the turned male blank diameter or units are unknown")
    elif isinstance(band, list) and len(band) == 2 and all(map(number, band)):
        if diameter < band[0] - 1e-6 / scale or diameter > band[1] + 1e-6 / scale:
            errors.append("turned male blank diameter differs from the external thread")
    elif "dia" in feature:
        unknown.append("the required male blank diameter band is unknown")
    elif number(nominal):
        if not same_length(diameter * scale, nominal * scale):
            errors.append("turned male blank diameter differs from the external thread")
    else:
        unknown.append("the required male blank diameter is unknown")
    at, axis = _geometry(bundle, name)
    length = feature.get("nominal_length", feature.get("length_nominal", feature.get("length")))
    start, end = cut.get("z_from"), cut.get("z_to")
    if at is None or axis is None or not number(length):
        unknown.append("the male thread shoulder location, axis or length is unknown")
    else:
        frame = setup_frame(bundle, other)
        first = frame_point(at, frame)
        last = frame_point([a + d * length for a, d in zip(at, axis, strict=True)], frame)
        if not all(map(number, first + last)) or scale is None:
            unknown.append("the male blank shoulder in the turning setup is unknown")
        elif not all(same_length(first[i] * scale, last[i] * scale) for i in (0, 1)):
            errors.append("male thread axis is not along the blank turning setup axis")
        elif not (number(start) and number(end)):
            unknown.append("the turned male blank axial extent is unknown")
        elif (
            min(start, end) > min(first[2], last[2]) + 1e-6 / scale
            or max(start, end) < max(first[2], last[2]) - 1e-6 / scale
        ):
            errors.append("turned male blank does not cover the external thread shoulder")
    return errors, unknown, _label(other, cut)


def evaluate(bundle):
    result = []
    starts, unsure = _banded_starts(bundle)
    all_ops = operations(bundle)
    positions = {id(op): index for index, (_, op) in enumerate(all_ops)}
    for name, feature in bundle.feature_definitions.items():
        route = operations(bundle, name)
        actions = [op["do"] for _, op in route]
        kind = feature["kind"]
        nums = {
            "kind": kind,
            "ops": [_label(s, o) for s, o in route],
            "chain": actions,
        }
        banded, maybe = starts.get(name, []), unsure.get(name, [])
        if banded:
            nums["banded_starts"] = banded
        if maybe:
            nums["unknown_starts"] = maybe
        cite = ["PLAN.md §4.1 op chain", "plan authored route", "features declared process/thread"]
        errors, unknown = list(banded), list(maybe)
        if UNKNOWN in actions:
            unknown.append("a route operation action is explicitly unknown")
        if kind == UNKNOWN:
            unknown.append("feature kind is explicitly unknown")
        elif kind == "external_thread":
            thread = feature.get("thread", UNKNOWN)
            known_thread = match(thread, thread) is True
            if not known_thread:
                unknown.append("the external thread designation is unresolved")
            if "die_thread" not in actions:
                if known_thread:
                    (unknown if UNKNOWN in actions else errors).append(
                        "external thread requires a die_thread operation"
                    )
                else:
                    unknown.append("external thread die preparation is unresolved")
            wrong = set(actions) & (
                {"spot", "center_drill", "drill", "ream", "counterbore"} | TAP_OPS
            )
            if wrong:
                errors.append(
                    "external thread cannot use an internal hole chain: " + ", ".join(sorted(wrong))
                )
            preparations = {}
            for setup, op in route:
                if op["do"] != "die_thread":
                    continue
                if _material(bundle, setup, setup, name, op=op, producer_op=op) is False:
                    errors.append("external thread die operation is on different retained material")
                bad, debt, producer = _turned_blank(bundle, setup, op, name, all_ops, positions)
                errors.extend(bad)
                unknown.extend(debt)
                preparations[_label(setup, op)] = producer
            if preparations:
                nums["male_blank_preparation"] = preparations
        elif kind in {"hole", "thread", "threaded_hole", "counterbore"}:
            parent = (
                feature.get("hole", feature.get("parent", name)) if kind == "counterbore" else name
            )
            parent_route = operations(bundle, parent)
            parent_actions = [op["do"] for _, op in parent_route]
            drills = [(s, o) for s, o in parent_route if o["do"] == "drill"]
            if not drills:
                (unknown if UNKNOWN in parent_actions else errors).append("no drill operation")
            witnesses, prepared = [], {}
            for setup, op in drills:
                bad, debt, source, proof = _drill_preparation(
                    bundle, setup, op, parent, all_ops, positions, prepared
                )
                prepared[id(op)] = (bad, debt, source, proof)
                errors.extend(bad)
                unknown.extend(debt)
                if proof is not None:
                    witnesses.append(proof)
            if not drills and not any(o["do"] == "spot" for _, o in parent_route):
                (unknown if UNKNOWN in parent_actions else errors).append("no spot operation")
            if feature.get("process") == "ream" and "ream" not in actions:
                (unknown if UNKNOWN in actions else errors).append("required ream operation absent")
            if feature.get("thread") == UNKNOWN or feature.get("process") == UNKNOWN:
                unknown.append("thread or finishing process is unresolved")
            threaded = feature.get("thread") not in (None, "", UNKNOWN) or kind in {
                "thread",
                "threaded_hole",
            }
            if threaded and not any(action in TAP_OPS for action in actions):
                (unknown if UNKNOWN in actions else errors).append(
                    "thread requires a tap or hand_tap operation"
                )
            if (kind == "counterbore" or "counterbore" in actions) and "counterbore" not in actions:
                (unknown if UNKNOWN in actions else errors).append("counterbore operation absent")
            measurements, tap_checks = {}, []
            for setup, op in route:
                if "prerequisites" in op and op["do"] != "drill":
                    bad, debt, proof = _spot_witness(bundle, setup, op, parent, all_ops, positions)
                    errors.extend(bad)
                    unknown.extend(debt)
                    witnesses.append(proof)
                if op["do"] not in TAP_OPS | {"ream", "counterbore"}:
                    continue
                _, drill, material = _earlier(
                    bundle, setup, op, parent, "drill", all_ops, positions
                )
                if material is False:
                    errors.append(
                        f"{_label(setup, op)} has no earlier drill operation on its material"
                    )
                elif material is None:
                    unknown.append(f"{_label(setup, op)} prior drill material is unresolved")
                if op["do"] not in TAP_OPS:
                    continue
                thread = feature.get("thread", UNKNOWN)
                expected = (
                    thread.get("tap_drill_mm", thread.get("drill_dia_mm", UNKNOWN))
                    if isinstance(thread, dict)
                    else feature.get("tap_drill_mm", UNKNOWN)
                )
                tool = resolve(bundle, "tools", drill.get("tool")) if drill else None
                actual = length_mm(tool, "dia") if tool else UNKNOWN
                nums.update(tap_drill_mm=expected, selected_drill_mm=actual)
                if (
                    material is not True
                    or not number(expected)
                    or not number(actual)
                    or not tool
                    or uncertain(tool)
                ):
                    unknown.append("thread tap-drill specification/measurement is unresolved")
                elif not same_length(expected, actual):
                    errors.append("selected tap drill differs from thread specification")
                if tool:
                    category, identity, _ = select(bundle, drill.get("tool"), "tools")
                    debt = length_debt(tool, "dia", category, identity)
                    if debt is not None:
                        measurements[debt["id"]] = debt
                tap = record(resolve(bundle, "tools", op.get("tool")))
                designation = match(thread, tap.get("thread"))
                hand, actual_hand = feature.get("thread_hand"), tap.get("thread_hand")
                required_class = feature.get("thread_class", UNKNOWN)
                selected_class = tap.get("thread_class", UNKNOWN)
                class_status = selected_class_status(
                    feature, tap, acceptance=thread_class_acceptance(bundle, name)
                )
                class_match = {"match": True, "mismatch": False}.get(class_status)
                tap_checks.append(
                    {
                        "operation": _label(setup, op),
                        "required": thread,
                        "selected": tap.get("thread", UNKNOWN),
                        "thread_match": designation,
                        "required_hand": hand or UNKNOWN,
                        "selected_hand": actual_hand or UNKNOWN,
                        "required_class": required_class,
                        "selected_class": selected_class,
                        "class_match": class_match,
                    }
                )
                if class_status == "not_adopted":
                    tap_checks[-1]["class_adoption"] = "not_adopted"
                if designation is False:
                    errors.append("selected tap thread differs from feature thread designation")
                elif designation is None:
                    unknown.append("feature or selected tap thread designation is unresolved")
                if hand in {"right", "left"} and actual_hand in {"right", "left"}:
                    if hand != actual_hand:
                        errors.append("selected tap hand differs from feature thread hand")
                else:
                    unknown.append("feature or selected tap thread hand is unresolved")
                if class_match is False:
                    errors.append("selected tap class differs from feature thread class")
                elif class_status == UNKNOWN:
                    unknown.append("feature or selected tap thread class is unresolved")
                if not tap or uncertain(tap):
                    unknown.append("the selected tap identity is unresolved or unconfirmed")
            if measurements:
                nums["measurements"] = list(measurements.values())
            if tap_checks:
                nums["tap_tools"] = tap_checks
            if witnesses:
                nums["preparation_witnesses"] = witnesses
        else:
            result.append(
                Finding(
                    "op_chain",
                    name,
                    "error" if errors else "unknown" if unknown else "not_applicable",
                    nums,
                    cite,
                    f"{name}: " + ("; ".join(errors or unknown) or "not a hole chain") + ".",
                )
            )
            continue
        status = "error" if errors else "unknown" if unknown else "pass"
        if unknown:
            nums["unresolved"] = list(dict.fromkeys(unknown))
        why = "; ".join(dict.fromkeys(errors or unknown)) or (
            "external thread has a prior turned male blank and die operation"
            if kind == "external_thread"
            else "hole prerequisites are present across the route"
        )
        result.append(Finding("op_chain", name, status, nums, cite, f"{name}: {why}."))
    return result
