"""Check authored execution order, not numeric operation sorting."""

from ..findings import Finding
from .resolution import (
    HAND_THREAD,
    MANUAL,
    TAP_OPS,
    op_feature,
    operation_material_status,
    operation_members,
    operations,
    record,
)


def evaluate(bundle):
    result = []
    route = operations(bundle)
    for setup in bundle.plan["setups"]:
        errors, unknown = [], []
        sid = setup["id"]
        own = setup["ops"]
        if any(o["do"] == "unknown" for o in own):
            nums = {"sequence": [f"{o['op']} {o['do']} {o.get('feature', '')}" for o in own]}
            result.append(
                Finding(
                    "order",
                    sid,
                    "unknown",
                    nums,
                    ["PLAN.md §4.1 order", "plan authored operation actions"],
                    f"{sid}: operation order cannot be established while an action is "
                    "explicitly unknown.",
                )
            )
            continue
        for index, (current_setup, op) in enumerate(route):
            if current_setup["id"] != sid:
                continue
            before = route[:index]
            after = route[index + 1 :]
            feature = op_feature(op)
            action = op["do"]
            spec = bundle.feature_definitions.get(feature, {})
            prerequisite_feature = (
                spec.get("hole", spec.get("parent", feature))
                if action == "counterbore"
                else feature
            )
            if action in TAP_OPS | {"ream", "counterbore"}:
                if not any(
                    prev.get("feature") == prerequisite_feature and prev["do"] == "drill"
                    for _, prev in before
                ):
                    errors.append(f"op {op['op']} {action} precedes its drill")
            if action == "drill" and any(
                o.get("feature") == feature
                and o["do"] == "spot"
                and operation_material_status(bundle, s, setup, feature, op=o, producer_op=op)
                is not False
                for s, o in after
            ):
                spotted = [
                    operation_material_status(bundle, setup, s, feature, op=op, producer_op=o)
                    for s, o in before
                    if o.get("feature") == feature and o["do"] == "spot"
                ]
                if True not in spotted:
                    (unknown if None in spotted else errors).append(
                        f"op {op['op']} drills before its spot"
                    )
            if action == "spot":
                # Face the entry surface in this setup, or explicitly receive a prior setup's
                # faced stock.
                faces = [
                    (s, o)
                    for s, o in route
                    if o["do"] in {"face", "finish_face"}
                    and operation_material_status(
                        bundle, setup, s, op_feature(o), op=op, producer_op=o
                    )
                    is not False
                ]
                if any(s["id"] == sid for s, _ in faces) and not any(
                    s["id"] == sid and (s, o) in faces for s, o in before
                ):
                    errors.append(f"op {op['op']} spots before facing")
            if action.startswith("rough_"):
                base = action.removeprefix("rough_")
                if any(
                    s["id"] == sid
                    and prev.get("feature") == feature
                    and prev["do"] == "finish_" + base
                    and operation_material_status(
                        bundle, setup, s, feature, op=op, producer_op=prev
                    )
                    is not False
                    for s, prev in before
                ):
                    errors.append(f"op {op['op']} roughs after finishing {feature}")
            # Release/part-off ends this holding; the next setup may cut the released part.
            if action in {"release", "part_off"} and any(
                s["id"] == sid and later["do"] not in MANUAL - HAND_THREAD for s, later in after
            ):
                errors.append(f"op {op['op']} releases before the final cutting operation")
            if action in TAP_OPS | {"ream", "counterbore"}:
                earlier = [
                    (s, o)
                    for s, o in before
                    if o.get("feature") == prerequisite_feature and o["do"] == "drill"
                ]
                prepared = [
                    operation_material_status(
                        bundle, setup, source, prerequisite_feature, op=op, producer_op=cut
                    )
                    for source, cut in earlier
                ]
                if earlier and True not in prepared:
                    if None in prepared:
                        unknown.append(
                            f"op {op['op']} drill survival after partition is unresolved"
                        )
                    else:
                        transfer = record(record(setup.get("zero")).get("transfer"))
                        drilled_ids = {s["id"] for s, _ in earlier}
                        # A legacy datum transfer cannot certify an explicit material route.
                        if (
                            "stock_in" in setup
                            or operation_members(bundle, setup, op) != ()
                            or transfer.get("from") not in drilled_ids
                        ):
                            errors.append(
                                f"op {op['op']} has no incoming route from the drilled setup"
                            )
        nums = {
            "sequence": [f"{o['op']} {o['do']} {o.get('feature', '')}" for o in own],
            "violations": errors,
        }
        if unknown:
            nums["unresolved"] = unknown
        result.append(
            Finding(
                "order",
                sid,
                "error" if errors else "unknown" if unknown else "pass",
                nums,
                ["PLAN.md §4.1 order", "plan setup/operation sequence and stock_in/zero.transfer"],
                f"{sid}: "
                + (
                    "; ".join(errors)
                    if errors
                    else "; ".join(unknown)
                    if unknown
                    else "rough/finish, face/spot, hole and release order is consistent"
                )
                + ".",
            )
        )
    return result
