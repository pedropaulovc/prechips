"""Drawing-owned construction permission; omitted plan intent is unknown."""

from prechips.findings import Finding
from prechips.rules.resolution import UNKNOWN


def evaluate(bundle):
    candidate = bundle.plan.get("construction", UNKNOWN)
    permission = bundle.features.get("construction", UNKNOWN)
    source = bundle.features.get("cite", [])
    if isinstance(source, dict):
        source = source.get("construction", [])
    source = source if isinstance(source, list) else [source]
    cite = ["PLAN.md §4.5 stock-form comparison, lines 573–577"] + [
        entry
        for entry in source
        if isinstance(entry, str) and entry.strip() and entry.strip() != UNKNOWN
    ]
    numbers = {"plan_construction": candidate, "drawing_construction": permission}
    if candidate == UNKNOWN or permission == UNKNOWN or not permission.strip():
        status = "unknown"
        sentence = "Candidate construction or drawing construction permission is unknown."
    elif candidate == "built_up" and permission != "built_up_permitted":
        status = "error"
        sentence = "drawing permits one-piece only"
    elif candidate == "one_piece" or (
        candidate == "built_up" and permission == "built_up_permitted"
    ):
        status = "pass"
        sentence = (
            "The candidate uses one-piece construction."
            if candidate == "one_piece"
            else "The drawing explicitly permits built-up construction."
        )
    else:
        status = "unknown"
        sentence = "Candidate construction is unresolved."
    return [Finding("construction", bundle.plan["part"], status, numbers, cite, sentence)]
