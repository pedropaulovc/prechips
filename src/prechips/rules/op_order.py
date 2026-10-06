"""Check authored execution order, not numeric operation sorting."""

from ..findings import Finding
from .resolution import MANUAL, operations, record


def evaluate(bundle):
    result = []
    route = operations(bundle)
    for setup in bundle.plan["setups"]:
        errors = []
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
            feature = op.get("feature")
            action = op["do"]
            spec = bundle.features["features"].get(feature, {})
            prerequisite_feature = (
                spec.get("hole", spec.get("parent", feature))
                if action == "counterbore"
                else feature
            )
            if action in {"ream", "tap", "counterbore"}:
                if not any(
                    prev.get("feature") == prerequisite_feature and prev["do"] == "drill"
                    for _, prev in before
                ):
                    errors.append(f"op {op['op']} {action} precedes its drill")
            if (
                action == "drill"
                and any(o.get("feature") == feature and o["do"] == "spot" for _, o in after)
                and not any(o.get("feature") == feature and o["do"] == "spot" for _, o in before)
            ):
                errors.append(f"op {op['op']} drills before its spot")
            if action == "spot":
                # Face the entry surface in this setup, or explicitly receive a prior setup's
                # faced stock.
                faces = [(s, o) for s, o in route if o["do"] in {"face", "finish_face"}]
                if any(s["id"] == sid for s, _ in faces) and not any(
                    s["id"] == sid and o["do"] in {"face", "finish_face"} for s, o in before
                ):
                    errors.append(f"op {op['op']} spots before facing")
            if action.startswith("rough_"):
                base = action.removeprefix("rough_")
                if any(
                    s["id"] == sid
                    and prev.get("feature") == feature
                    and prev["do"] == "finish_" + base
                    for s, prev in before
                ):
                    errors.append(f"op {op['op']} roughs after finishing {feature}")
            # Release/part-off ends this holding; the next setup may cut the released part.
            if action in {"release", "part_off"} and any(
                s["id"] == sid and later["do"] not in MANUAL for s, later in after
            ):
                errors.append(f"op {op['op']} releases before the final cutting operation")
            if action in {"ream", "tap", "counterbore"}:
                earlier = [
                    (s, o)
                    for s, o in before
                    if o.get("feature") == prerequisite_feature and o["do"] == "drill"
                ]
                if earlier and earlier[-1][0]["id"] != sid:
                    transfer = record(record(setup.get("zero")).get("transfer"))
                    source = setup.get("stock_in")
                    sources = source if isinstance(source, list) else [source]
                    earlier_ids = {s["id"] for s, _ in before}
                    if (
                        not any(ref in earlier_ids for ref in sources)
                        and transfer.get("from") not in earlier_ids
                    ):
                        errors.append(f"op {op['op']} has no incoming route from the drilled setup")
        nums = {
            "sequence": [f"{o['op']} {o['do']} {o.get('feature', '')}" for o in own],
            "violations": errors,
        }
        result.append(
            Finding(
                "order",
                sid,
                "error" if errors else "pass",
                nums,
                ["PLAN.md §4.1 order", "plan setup/operation sequence and stock_in/zero.transfer"],
                f"{sid}: "
                + (
                    "; ".join(errors)
                    if errors
                    else "rough/finish, face/spot, hole and release order is consistent"
                )
                + ".",
            )
        )
    return result
