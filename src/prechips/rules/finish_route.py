"""A drawing finish is route work: a declared finish needs a coating step (PLAN §4.1).

The drawing's ``material.finish`` (black oxide, paint, oil) is a requirement on the
delivered part, not a note. A route with no ``coating`` op never applies it, and a cut
after the coating removes it, so the job cannot pass silently. Every cut needs a coating
after it, in plan order, on stock that carries that cut: the same setup, or a setup whose
``stock_in`` lineage contains it. On a built-up part each component is covered by its own
coating, or by one coating of the joined assembly. An op of explicitly unknown action, or
undeclared routing, leaves its coverage unknown. Whether each coating op's process
resolves to an outside service or in-house consumables is ``tool_resolves``'s per-op check.
"""

from ..findings import Finding
from ..joint_features import _lineage
from .geometry_common import cutting_action
from .resolution import UNKNOWN, operations, record

CITE = ["features.material.finish", "plan coating ops", "PLAN.md §4.1 finishing route"]


def evaluate(bundle):
    subject = bundle.plan["part"]
    material = record(bundle.features.get("material"))
    finish = material.get("finish")
    plan = bundle.plan
    route = operations(bundle)
    lineage = {setup["id"]: _lineage(plan, setup["id"]) for setup in plan["setups"]}
    declared = {setup["id"] for setup in plan["setups"] if "stock_in" in setup}
    routed = {sid: members <= declared for sid, members in lineage.items()}
    coatings = [index for index, (_, op) in enumerate(route) if op["do"] == "coating"]

    def label(index):
        return f"{route[index][0]['id']}:{route[index][1]['op']}"

    def coated(index):
        """True, False, or None (a later coating whose routing is undeclared)."""
        sid = route[index][0]["id"]
        later = [lineage[route[j][0]["id"]] for j in coatings if j > index]
        if any(sid in members for members in later):
            return True
        if any(not routed[route[j][0]["id"]] for j in coatings if j > index):
            return None
        return False

    cuts = [index for index, (_, op) in enumerate(route) if cutting_action(op) is not False]
    coverage = {index: coated(index) for index in cuts}
    uncoated = [i for i in cuts if coverage[i] is False and cutting_action(route[i][1])]
    unresolved = [i for i in cuts if coverage[i] is not True and i not in uncoated]
    numbers = {
        "finish": finish if isinstance(finish, str) else "not_declared",
        "ops": [label(i) for i in coatings],
        "uncoated_cuts": [label(i) for i in uncoated],
        "unresolved_cuts": [label(i) for i in unresolved],
    }
    if not isinstance(finish, str) or not finish.strip():
        status, message = "not_applicable", "the drawing declares no finish"
    elif finish.strip() == UNKNOWN:
        status, message = "unknown", "the drawing finish is explicitly unknown"
    elif not coatings:
        status = "warn"
        message = f"the drawing finish ({finish.strip()}) has no coating step in the route"
    elif uncoated:
        status = "warn"
        message = (
            f"the drawing finish ({finish.strip()}) is cut away: no coating follows "
            f"{', '.join(label(i) for i in uncoated)} on its stock"
        )
    elif unresolved:
        status = "unknown"
        message = (
            f"the drawing finish ({finish.strip()}) coverage is unresolved after "
            f"{', '.join(label(i) for i in unresolved)} (unknown action or undeclared routing)"
        )
    else:
        status = "pass"
        message = (
            f"the drawing finish is applied by coating op {', '.join(label(i) for i in coatings)}"
        )
    return [Finding("finish_route", subject, status, numbers, CITE, f"{subject}: {message}.")]
