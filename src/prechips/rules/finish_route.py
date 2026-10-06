"""A drawing finish is route work: a declared finish needs a coating step (PLAN §4.1).

The drawing's ``material.finish`` (black oxide, paint, oil) is a requirement on the
delivered part, not a note. A route with no ``coating`` op never applies it, so the job
cannot pass silently; whether each coating op's process resolves to an outside service
or in-house consumables is ``tool_resolves``'s per-op check.
"""

from ..findings import Finding
from .resolution import UNKNOWN, operations, record

CITE = ["features.material.finish", "plan coating ops", "PLAN.md §4.1 finishing route"]


def evaluate(bundle):
    subject = bundle.plan["part"]
    material = record(bundle.features.get("material"))
    finish = material.get("finish")
    coatings = [
        f"{setup['id']}:{op['op']}" for setup, op in operations(bundle) if op["do"] == "coating"
    ]
    numbers = {"finish": finish if isinstance(finish, str) else "not_declared", "ops": coatings}
    if not isinstance(finish, str) or not finish.strip():
        status, message = "not_applicable", "the drawing declares no finish"
    elif finish.strip() == UNKNOWN:
        status, message = "unknown", "the drawing finish is explicitly unknown"
    elif not coatings:
        status = "warn"
        message = f"the drawing finish ({finish.strip()}) has no coating step in the route"
    else:
        status = "pass"
        message = f"the drawing finish is applied by coating op {', '.join(coatings)}"
    return [Finding("finish_route", subject, status, numbers, CITE, f"{subject}: {message}.")]
