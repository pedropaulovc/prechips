"""A drawing finish is route work: a declared finish needs a coating step (PLAN §4.1).

The drawing's ``material.finish`` (black oxide, paint, oil) is a requirement on the
delivered part, not a note. A route with no ``coating`` op never applies it, and a coating
followed by a cut is cut away, so the job cannot pass silently: only a coating after the
route's last cut applies the finish (after an op of unknown action, it is unknown). Whether
each coating op's process resolves to an outside service or in-house consumables is
``tool_resolves``'s per-op check.
"""

from ..findings import Finding
from .geometry_common import cutting_action
from .resolution import UNKNOWN, operations, record

CITE = ["features.material.finish", "plan coating ops", "PLAN.md §4.1 finishing route"]


def evaluate(bundle):
    subject = bundle.plan["part"]
    material = record(bundle.features.get("material"))
    finish = material.get("finish")
    route = operations(bundle)
    coatings = [index for index, (_, op) in enumerate(route) if op["do"] == "coating"]
    # Route order is plan order; the last op that cuts, and the last that may (unknown action).
    cuts = [index for index, (_, op) in enumerate(route) if cutting_action(op) is True]
    maybe = [index for index, (_, op) in enumerate(route) if cutting_action(op) is not False]
    last_cut, last_maybe = (cuts or [-1])[-1], (maybe or [-1])[-1]
    applied = [index for index in coatings if index > last_maybe]
    pending = [index for index in coatings if last_cut < index < last_maybe]

    def names(indices):
        return [f"{route[i][0]['id']}:{route[i][1]['op']}" for i in indices]

    numbers = {
        "finish": finish if isinstance(finish, str) else "not_declared",
        "ops": names(coatings),
        "applied_after_last_cut": names(applied),
    }
    if not isinstance(finish, str) or not finish.strip():
        status, message = "not_applicable", "the drawing declares no finish"
    elif finish.strip() == UNKNOWN:
        status, message = "unknown", "the drawing finish is explicitly unknown"
    elif applied:
        status = "pass"
        message = f"the drawing finish is applied by coating op {', '.join(names(applied))}"
    elif pending:
        status = "unknown"
        message = (
            f"the drawing finish ({finish.strip()}) coating {', '.join(names(pending))} is "
            "followed by an op of unknown action"
        )
    elif coatings:
        status = "warn"
        message = (
            f"the drawing finish ({finish.strip()}) coating {', '.join(names(coatings))} is "
            f"cut away by {names([last_cut])[0]}; no coating step follows the last cut"
        )
    else:
        status = "warn"
        message = f"the drawing finish ({finish.strip()}) has no coating step in the route"
    return [Finding("finish_route", subject, status, numbers, CITE, f"{subject}: {message}.")]
