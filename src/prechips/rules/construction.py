"""Drawing-owned construction permission; only an explicit note permits built-up."""

from prechips.findings import Finding
from prechips.rules.resolution import UNKNOWN, _citations


def evaluate(bundle):
    candidate = bundle.plan.get("construction", UNKNOWN)
    permission = bundle.features.get("construction", UNKNOWN)
    cite = ["PLAN.md §4.5 stock-form comparison, lines 573–577"] + _citations(
        bundle.features.get("cite"), "construction"
    )
    numbers = {"plan_construction": candidate, "drawing_construction": permission}
    if candidate == "built_up" and permission != "built_up_permitted":
        status = "error"
        sentence = "drawing permits one-piece only"
    elif candidate == "built_up":
        status = "pass"
        sentence = "The drawing explicitly permits built-up construction."
    elif candidate == "one_piece":
        status = "pass"
        sentence = "The candidate uses one-piece construction."
    else:
        status = "unknown"
        sentence = "Candidate construction is unknown."
    return [Finding("construction", bundle.plan["part"], status, numbers, cite, sentence)]
