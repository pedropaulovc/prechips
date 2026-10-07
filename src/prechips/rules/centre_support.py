"""A dead centre rides in a centre the arriving stock already has (PLAN §4.1 holding).

A lathe hold whose ``support`` is a centre fixture names the plan
``process_features`` centre it seats in (``hold.centre_hole``). The centre must be
made by a ``center_drill`` op of an earlier setup in this setup's ``stock_in``
lineage, and its countersink mouth must be the ``centre_hole_dia_mm`` the hold seats
the point in. An undeclared centre, mouth or routing is unknown; a centre no earlier
lineage op makes, or a mouth that differs, is an error. The kernel separately checks
that the point touches the cut countersink without interpenetration.
"""

from prechips.findings import Finding
from prechips.joint_features import _lineage
from prechips.process_features import ACTIONS, centre_depth_mm, label, process_of
from prechips.rules.resolution import (
    UNKNOWN,
    number,
    record,
    resolve,
    same_length,
    workholding_category,
)

CENTRE_KINDS = frozenset({"dead_centre", "dead_center", "live_centre", "live_center"})
_CITE = "PLAN.md §4.1 hold fields: hold.centre_hole and centre_hole_dia_mm"


def _centre_support(bundle, hold):
    """Whether ``hold`` rides on a centre: a centre-kind support or a declared seat."""
    reference = hold.get("support", UNKNOWN)
    item = record(resolve(bundle, workholding_category(bundle, reference), reference))
    return item.get("kind") in CENTRE_KINDS or any(
        key in hold for key in ("centre_hole", "centre_hole_dia_mm")
    )


def _makers(bundle, setup, name):
    """``(earlier, later)`` op labels that drill centre ``name`` relative to ``setup``."""
    earlier = _lineage(bundle.plan, setup["id"]) - {setup["id"]}
    before, after = [], []
    for other in bundle.plan["setups"]:
        for op in other["ops"]:
            if op.get("feature") != name or op.get("do") not in ACTIONS["centre_hole"]:
                continue
            (before if other["id"] in earlier else after).append(f"{other['id']} op {op['op']}")
    return before, after


def _evaluate(bundle, setup, hold):
    name = hold.get("centre_hole", UNKNOWN)
    seat = hold.get("centre_hole_dia_mm", UNKNOWN)
    numbers = {"support": hold.get("support", UNKNOWN), "centre_hole": name}
    numbers["hold_centre_hole_dia_mm"] = seat
    if name == UNKNOWN:
        return "unknown", numbers, "which centre the dead centre rides in is undeclared"
    process = process_of(bundle.feature_definitions.get(name)) or {}
    mouth = process.get("mouth_dia_mm", UNKNOWN)
    before, after = _makers(bundle, setup, name)
    lineage = _lineage(bundle.plan, setup["id"])
    routed = all("stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage)
    numbers.update(
        {
            "process_feature": label(name),
            "made_by": before,
            "made_later": after,
            "mouth_dia_mm": mouth,
            **centre_depth_mm(bundle.feature_definitions.get(name)),
        }
    )
    errors = []
    if not before and routed:
        made = f"it is first drilled in {after[0]}" if after else "no op drills it"
        errors.append(f"no earlier setup in its stock lineage drills {name}; {made}")
    if number(seat) and number(mouth) and not same_length(seat, mouth):
        errors.append(
            f"the hold seats the point in a Ø{seat:g} mouth but {name} is drilled to Ø{mouth:g}"
        )
    if errors:
        return "error", numbers, "; ".join(errors)
    if not before:
        return "unknown", numbers, f"whether the arriving stock already has {name} is unresolved"
    if not (number(seat) and number(mouth)):
        return "unknown", numbers, f"the seat or mouth diameter of {name} is unresolved"
    return "pass", numbers, f"the dead centre rides in {name}, drilled in {before[-1]}"


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        hold = setup.get("hold")
        if not isinstance(hold, dict) or not _centre_support(bundle, hold):
            findings.append(
                Finding(
                    "centre_support",
                    setup["id"],
                    "not_applicable",
                    {},
                    [_CITE],
                    f"{setup['id']}: the work is not carried on a centre.",
                )
            )
            continue
        status, numbers, why = _evaluate(bundle, setup, hold)
        findings.append(
            Finding(
                "centre_support", setup["id"], status, numbers, [_CITE], f"{setup['id']}: {why}."
            )
        )
    return findings
