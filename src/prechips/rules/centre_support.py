"""A centre rides in a centre the arriving stock already has (PLAN §4.1 holding).

Always required (findings.ALWAYS_REQUIRED) wherever it applies: a hold whose ``support`` or
any ``supports`` entry is a dead or live centre, or that declares the centre it seats in,
names the plan ``process_features`` centre the point rides in (``hold.centre_hole``). The
centre must be made by a ``center_drill`` op of an earlier setup in this setup's
``stock_in`` lineage, that op's own ``blind_depth`` verdict must pass (``tip_endpoints``:
the selected tool's own centre, its mouth on the touched entry surface) and its countersink
mouth must be the ``centre_hole_dia_mm`` the hold seats the point in. An undeclared
centre, mouth, routing anywhere in the lineage, or preparation is unknown; a centre no
earlier lineage op makes, a preparation contradiction, or a mouth that differs is an
error. A support is a centre when its inventory kind names a centre (a ``centre`` /
``center`` word: dead, live, tailstock centre) or is a ``tailstock``, which carries work
only on its centre, or, for a machine accessory with no record, when its name does; the
word ``tailstock`` alone in a name (a tailstock drill chuck or quill) is not one. A
support whose identity is unresolved (unknown, not in the inventory, or of unknown kind)
may be one; so may each centre beyond the one ``centre_hole`` a hold names. Any of those
keeps the finding unknown unless an error is established. A support of a known non-centre
kind is not one, whatever verification or measurement debt its record carries: that debt
is its own checks'. A hold none of whose supports is (or may be) a centre is not
applicable. A wholly undeclared hold names no support to check: its debt is
``hold_fields``', as an unrouted setup's is stock routing's rather than ``joint_fit``'s.
The kernel separately checks that the point touches the cut countersink without
interpenetration.
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
)
from prechips.rules.tip_endpoints import centre_check

# A whole ``centre`` / ``center`` word in a kind or accessory name: a dead, live, tailstock
# or pipe centre, never a self-centering chuck.
_CENTRE_WORD = re.compile(r"(?:^|[^a-z])(?:centre|center)(?:$|[^a-z])", re.IGNORECASE)
# Declared no-support sentinels.
_NO_SUPPORT = frozenset({"none", "not_applicable"})
_CITE = "PLAN.md §4.1 hold fields: hold.centre_hole and centre_hole_dia_mm"


def _is_centre(kind, reference):
    """Whether a support of inventory ``kind`` named ``reference`` carries work on a centre.

    The kind says so (a centre word, or a ``tailstock``, which carries work only on its
    centre); a machine accessory has no record, so its name must name a centre.
    """
    if kind == "tailstock":
        return True
    return bool(_CENTRE_WORD.search(reference if kind == "accessory" else kind))


def _supports(hold):
    """Every support reference ``hold`` declares: ``support`` and each ``supports`` ref."""
    values = [hold["support"]] if "support" in hold else []
    supports = hold.get("supports", [])
    values += supports if isinstance(supports, list) else [supports]
    return [value.get("ref", UNKNOWN) if isinstance(value, dict) else value for value in values]


def _centres(bundle, hold):
    """``(centres, unresolved)``: the distinct ``hold`` supports that are centres
    (``_is_centre``), plus the hold's ``support`` if it declares the centre it seats in; and
    the support references whose identity is unresolved (unknown, not in the inventory, or
    of unknown kind), any of which may be a centre."""
    centres, unresolved = [], []
    for reference in _supports(hold):
        if not isinstance(reference, str) or reference in (UNKNOWN, ""):
            unresolved.append(reference)
            continue
        if reference in _NO_SUPPORT:
            continue
        item = resolve(bundle, "fixtures", reference)
        kind = record(item).get("kind", UNKNOWN)
        if item is None or not isinstance(kind, str) or kind == UNKNOWN:
            unresolved.append(reference)
        elif _is_centre(kind, reference):
            centres.append(reference)
    if not centres and any(key in hold for key in ("centre_hole", "centre_hole_dia_mm")):
        centres.append(hold.get("support", UNKNOWN))
    return list(dict.fromkeys(centres)), unresolved


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


def _open(centres, unresolved):
    """Why the hold's supports leave a seat unchecked beyond the one ``centre_hole`` names."""
    reasons = []
    if unresolved:
        reasons.append(
            "whether support "
            + ", ".join(repr(reference) for reference in unresolved)
            + " is a centre is unresolved: it is unknown, not in the inventory or of unknown "
            "kind"
        )
    if len(centres) > 1:
        reasons.append(
            f"the work rides on {len(centres)} centres ({', '.join(map(repr, centres))}) but "
            "the hold names one centre_hole, so the seat of each other centre is unresolved"
        )
    return reasons


def evaluate(bundle):
    findings = []
    for setup in bundle.plan["setups"]:
        hold = setup.get("hold")
        centres, unresolved = _centres(bundle, hold) if isinstance(hold, dict) else ([], [])
        if centres:
            status, numbers, why = _evaluate(bundle, setup, hold, centres)
        else:
            status, numbers, why = "not_applicable", {}, "the work is not carried on a centre"
        if unresolved:
            numbers["unresolved_supports"] = unresolved
        # An established contradiction stands; anything else a further support may be is
        # unresolved debt, never a pass or a proof that no centre is used.
        reasons = _open(centres, unresolved)
        if reasons and status != "error":
            why = "; ".join(reasons if status == "not_applicable" else [why, *reasons])
            status = "unknown"
        findings.append(
            Finding(
                "centre_support", setup["id"], status, numbers, [_CITE], f"{setup['id']}: {why}."
            )
        )
    return findings
