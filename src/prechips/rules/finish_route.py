"""A coating finish is route work: it needs a coating step (PLAN §4.1).

The drawing's ``material.finish`` is a coating requirement unless ``finish_kind``
explicitly declares a surface condition. Surface conditions belong to inspection,
not coating coverage. A route with no ``coating`` op never applies a coating finish,
and a cut after the coating removes it, so the job cannot pass silently. Every cut
needs a coating after it, in plan order, on all stock that carries that cut. Producer
history alone does not cover a retained partition's unsplit parent. On a built-up part
each component is covered by its own coating, or by one coating of the joined assembly.
An op of explicitly unknown action, undeclared routing, or unresolved partition coverage
leaves its coverage unknown. Whether each coating op's process
resolves to an outside service or in-house consumables is ``tool_resolves``'s per-op check.
"""

from ..findings import Finding
from ..material_routes import material_coverage_status, setup_lineage
from .geometry_common import cutting_action
from .resolution import UNKNOWN, operations, record

CITE = ["features.material.finish", "plan coating ops", "PLAN.md §4.1 finishing route"]


def evaluate(bundle):
    subject = bundle.plan["part"]
    material = record(bundle.features.get("material"))
    finish = material.get("finish")
    finish_kind = material.get("finish_kind", "coating")
    if finish_kind == UNKNOWN or (
        finish_kind == "surface"
        and isinstance(finish, str)
        and finish.strip()
        and finish.strip() != UNKNOWN
    ):
        status, message = (
            ("unknown", "the drawing finish kind is explicitly unknown")
            if finish_kind == UNKNOWN
            else (
                "not_applicable",
                "the drawing declares a surface condition, not a coating requirement; "
                "surface inspection is checked separately",
            )
        )
        return [
            Finding(
                "finish_route",
                subject,
                status,
                {"finish": finish, "finish_kind": finish_kind},
                ["features.material.finish", "features.material.finish_kind"],
                f"{subject}: {message}.",
            )
        ]
    plan = bundle.plan
    route = operations(bundle)
    lineage = {setup["id"]: setup_lineage(plan, setup["id"]) for setup in plan["setups"]}
    declared = {setup["id"] for setup in plan["setups"] if "stock_in" in setup}
    routed = {sid: members <= declared for sid, members in lineage.items()}
    coatings = [index for index, (_, op) in enumerate(route) if op["do"] == "coating"]

    def label(index):
        return f"{route[index][0]['id']}:{route[index][1]['op']}"

    def coated(index):
        """True, False, or None (a later coating whose material coverage is unresolved)."""
        sid = route[index][0]["id"]
        later = [route[j][0]["id"] for j in coatings if j > index]
        covering = [covering for covering in later if sid in lineage[covering]]
        coverage = material_coverage_status(plan, covering, sid) if covering else False
        if coverage is True:
            return True
        if coverage is None or any(not routed[covering] for covering in later):
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
