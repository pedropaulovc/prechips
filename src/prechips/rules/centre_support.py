"""A centre rides in a centre the arriving stock already has (PLAN §4.1 holding).

Always required (findings.ALWAYS_REQUIRED) wherever it applies: a hold whose ``support`` or
any ``supports`` entry is a dead or live centre, or that declares the centre it seats in,
names the plan ``process_features`` centre the point rides in (``hold.centre_hole``). The
centre must be made by a ``center_drill`` op of an earlier setup in this setup's
``stock_in`` lineage, that op's preparation must be established (``tip_endpoints``: the
selected tool's own centre, its mouth on the touched entry surface) and its countersink
mouth must be the ``centre_hole_dia_mm`` the hold seats the point in. An undeclared
centre, mouth, routing anywhere in the lineage, or preparation is unknown; a centre no
earlier lineage op makes, a preparation contradiction, or a mouth that differs is an
error. A hold none of whose supports is (or may be) a centre is not applicable; one with an
unknown or unresolvable support reference and no known centre is unknown. A wholly
undeclared hold names no support to check: its debt is ``hold_fields``', as an unrouted
setup's is stock routing's rather than ``joint_fit``'s. The kernel separately checks that
the point touches the cut countersink without interpenetration.
"""

import re

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
from prechips.rules.tip_endpoints import centre_check

CENTRE_KINDS = frozenset({"dead_centre", "dead_center", "live_centre", "live_center"})
# A machine accessory has no fixture record: a centre is named as one.
_CENTRE_NAME = re.compile(r"(?:^|[^a-z])(?:centre|center)(?:$|[^a-z])", re.IGNORECASE)
# Declared no-support sentinels.
_NO_SUPPORT = frozenset({"none", "not_applicable"})
_CITE = "PLAN.md §4.1 hold fields: hold.centre_hole and centre_hole_dia_mm"


def _supports(hold):
    """Every support reference ``hold`` declares: ``support`` and each ``supports`` ref."""
    values = [hold["support"]] if "support" in hold else []
    supports = hold.get("supports", [])
    values += supports if isinstance(supports, list) else [supports]
    return [value.get("ref", UNKNOWN) if isinstance(value, dict) else value for value in values]


def _centres(bundle, hold):
    """``(centres, unresolved)``: the ``hold`` supports that are dead or live centres (a
    centre fixture kind, or a machine accessory named a centre), plus the hold's ``support``
    if it declares the centre it seats in; and the unknown or unresolvable support
    references, any of which may be a centre."""
    centres, unresolved = [], []
    for reference in _supports(hold):
        if not isinstance(reference, str) or reference in (UNKNOWN, ""):
            unresolved.append(reference)
            continue
        if reference in _NO_SUPPORT:
            continue
        item = resolve(bundle, workholding_category(bundle, reference), reference)
        kind = record(item).get("kind")
        if kind in CENTRE_KINDS or (kind == "accessory" and _CENTRE_NAME.search(reference)):
            centres.append(reference)
        elif item is None:
            unresolved.append(reference)
    if not centres and any(key in hold for key in ("centre_hole", "centre_hole_dia_mm")):
        centres.append(hold.get("support", UNKNOWN))
    return centres, unresolved


def _makers(bundle, setup, name):
    """``(earlier (setup, op) pairs, later op labels)`` drilling centre ``name``."""
    earlier = _lineage(bundle.plan, setup["id"]) - {setup["id"]}
    before, after = [], []
    for other in bundle.plan["setups"]:
        for op in other["ops"]:
            if op.get("feature") != name or op.get("do") not in ACTIONS["centre_hole"]:
                continue
            if other["id"] in earlier:
                before.append((other, op))
            else:
                after.append(f"{other['id']} op {op['op']}")
    return before, after


def _evaluate(bundle, setup, hold, centres):
    name = hold.get("centre_hole", UNKNOWN)
    seat = hold.get("centre_hole_dia_mm", UNKNOWN)
    numbers = {"support": hold.get("support", UNKNOWN), "centres": centres, "centre_hole": name}
    numbers["hold_centre_hole_dia_mm"] = seat
    if name == UNKNOWN:
        return "unknown", numbers, "which centre the work rides in is undeclared"
    process = process_of(bundle.feature_definitions.get(name)) or {}
    mouth = process.get("mouth_dia_mm", UNKNOWN)
    before, after = _makers(bundle, setup, name)
    made_by = [f"{other['id']} op {op['op']}" for other, op in before]
    # A pass needs every setup the stock passes through routed: one undeclared stock_in
    # anywhere upstream leaves where the work (and any centre) came from unresolved.
    lineage = _lineage(bundle.plan, setup["id"])
    routed = all("stock_in" in other for other in bundle.plan["setups"] if other["id"] in lineage)
    preparation = {
        made: centre_check(bundle, other, op)
        for made, (other, op) in zip(made_by, before, strict=True)
    }
    numbers.update(
        {
            "process_feature": label(name),
            "made_by": made_by,
            "made_later": after,
            "routed": routed,
            "preparation": {made: status for made, (status, _) in preparation.items()},
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
    for made, (status, reasons) in preparation.items():
        if status == "error":
            errors.append(f"{made} does not prepare {name}: {'; '.join(reasons)}")
    if errors:
        return "error", numbers, "; ".join(errors)
    if not before:
        return "unknown", numbers, f"whether the arriving stock already has {name} is unresolved"
    if not routed:
        why = (
            "a setup in the stock lineage declares no stock_in, so whether the work arriving "
            f"here still carries {name} is unresolved"
        )
        return "unknown", numbers, why
    for made, (status, reasons) in preparation.items():
        if status != "pass":
            why = f"the preparation of {name} by {made} is unresolved: {'; '.join(reasons)}"
            return "unknown", numbers, why
    if not (number(seat) and number(mouth)):
        return "unknown", numbers, f"the seat or mouth diameter of {name} is unresolved"
    return "pass", numbers, f"the centre rides in {name}, drilled in {made_by[-1]}"


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        hold = setup.get("hold")
        centres, unresolved = _centres(bundle, hold) if isinstance(hold, dict) else ([], [])
        if centres:
            status, numbers, why = _evaluate(bundle, setup, hold, centres)
        elif unresolved:
            status, numbers = "unknown", {"unresolved_supports": unresolved}
            why = (
                "whether the work rides on a centre is unresolved: support "
                + ", ".join(repr(reference) for reference in unresolved)
                + " is unknown or not in the inventory"
            )
        else:
            status, numbers, why = "not_applicable", {}, "the work is not carried on a centre"
        findings.append(
            Finding(
                "centre_support", setup["id"], status, numbers, [_CITE], f"{setup['id']}: {why}."
            )
        )
    return findings
