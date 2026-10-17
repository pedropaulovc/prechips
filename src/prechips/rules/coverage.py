"""All imported faces need a cutting claim, an explicit as-stock declaration, or a joint
that forms them.

A joint's ``forms`` feature is credited to the joint only when the join assembles, the
kernel admits its joined corner inside the feature's own band (a sharp corner for a
``[0, r]`` radius band), and the last op naming the feature at or after the join checks
that band with a capable gauge (:func:`~prechips.rules.inspection.requirement_check`, a
limit leaf included). Without a passing check the credit is debt, never a pass; a
refused join credits nothing.
"""

from prechips.findings import Finding
from prechips.rules import blank_credit, inspection
from prechips.rules.geometry_common import (
    LATHE_APPROACH_REASON,
    ROTARY,
    approach,
    approach_model_reason,
    cutting_action,
    op_claims,
    provenance,
    rotary_debt_text,
    rotary_gap_text,
    rotary_union,
    unavailable,
)
from prechips.rules.resolution import (
    HAND_FINISH,
    SAW_OPS,
    UNKNOWN,
    claim_refs,
    known_refs,
    op_entry,
    op_feature,
    operations,
    record,
)

CLAIM_DEBT = "cutting claims are unknown, unmapped or undecided, or as-stock refs are unknown"
# The band a joint-formed feature's joined corner is admitted against and read in.
FORMED_REQUIREMENT = "radius"


def _downstream(plan, sid):
    """``sid`` and every setup whose stock descends from it."""
    found = {sid}
    for setup in plan["setups"]:
        refs = setup.get("stock_in")
        if any(ref in found for ref in (refs if isinstance(refs, list) else [refs])):
            found.add(setup["id"])
    return found


def _after_join(setup, op, sid):
    """Whether ``op`` runs once the joint ``sid`` has formed its corner: any op of a later
    setup, and in the joint's own setup an op after its first ``fit`` (the op that joins;
    a setup with none joins on entry). An inspection before the fit reads no joined
    corner."""
    if setup["id"] != sid:
        return True
    ops = setup["ops"]
    fits = [index for index, other in enumerate(ops) if other.get("do") == "fit"]
    position = next(index for index, other in enumerate(ops) if other is op)
    return not fits or position > fits[0]


def joint_formed(bundle, facts):
    """``(credited indices, debts, pending indices, rows)`` for every feature a joint
    ``forms``; ``pending`` are the faces whose credit is debt."""
    credited, debts, pending, rows = set(), [], set(), []
    mapping = record(facts.get("mapping"))
    for setup in bundle.plan["setups"]:
        joint = record(setup.get("joint"))
        sid = setup["id"]
        detail = record(record(facts.get("setups")).get(sid))
        later = _downstream(bundle.plan, sid)
        for name in joint.get("forms") or ():
            formed = record(record(detail.get("forms")).get(name))
            row = {"joint": sid, "feature": name, "kernel": formed.get("status", UNKNOWN)}
            rows.append(row)
            if detail.get("assembly_error"):
                # The refused join (joint_assembly's error) credits nothing: faces stay open.
                row["credit"] = "refused"
                continue
            refs = record(bundle.feature_definitions.get(name)).get("faces")
            faces = (
                {mapping[ref] for ref in refs if ref in mapping}
                if isinstance(refs, list)
                else set()
            )
            if formed.get("status") != "formed":
                why = formed.get("reason") or detail.get("stock_reason") or "join unresolved"
                debts.append(f"{sid} forms {name}, but its joined corner is unresolved ({why})")
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            # Only an op naming the feature checks it: an unscoped entry on another
            # feature's op reads that feature, never this corner.
            checks = [
                (s, o)
                for s, o in operations(bundle, name)
                if s["id"] in later
                and _after_join(s, o, sid)
                and op_entry(o, "checks", name, FORMED_REQUIREMENT) is not None
            ]
            if not checks:
                debts.append(
                    f"{sid} forms {name}, but no check after the join reads its "
                    f"{FORMED_REQUIREMENT} band"
                )
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            check_setup, op = checks[-1]
            status, message, _ = inspection.requirement_check(bundle, name, FORMED_REQUIREMENT, op)
            row.update(check=f"{check_setup['id']}:{op['op']}", check_status=status)
            if status != "pass":
                debts.append(
                    f"{sid} forms {name}, but its {FORMED_REQUIREMENT} check is not a pass "
                    f"({message})"
                )
                pending |= faces
                row["credit"] = UNKNOWN
                continue
            row["credit"] = "credited"
            credited.update(formed.get("indices", ()))
    return credited, debts, pending, rows


def evaluate(bundle):
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    subject = bundle.plan["part"]
    cite = provenance(bundle, "coverage") + [
        "plan.stock.as_is_faces; union of each cutting op's direction-valid face claims"
    ]
    blocked = unavailable(bundle, "coverage", subject, facts, cite)
    if blocked:
        return [blocked]
    faces = facts.get("faces")
    if not isinstance(faces, list) or not faces:
        return [
            Finding(
                "coverage",
                subject,
                "unknown",
                {},
                cite,
                "Imported STEP face inventory is unresolved.",
            )
        ]
    all_faces = {face["index"] for face in faces}
    claimed, rotary, errors, debt = set(), set(), [], False
    unsupported = set()
    mapping = record(facts.get("mapping"))
    for setup, op in operations(bundle):
        if record(record(bundle.feature_definitions.get(op_feature(op))).get("joint")):
            # Transient preparation, even with an explicit face override, credits only the
            # final STEP faces the kernel certifies its accepted finishing cut leaves.
            claimed.update(op_claims(bundle, facts, setup, op)[0] or ())
            continue
        if op.get("do") in SAW_OPS:
            # A saw cut removes stock; its kerf face is not credit toward target faces.
            continue
        action = cutting_action(op)
        if action is False and op.get("do") not in HAND_FINISH:
            continue
        if action is None:
            debt = True
            continue
        # Unsupported lathe claims are candidates only, never direction-valid credit.
        indices, _, invalid = op_claims(bundle, facts, setup, op)
        errors.extend(invalid)
        if indices is None:
            refs = claim_refs(bundle, op)
            if (
                approach_model_reason(bundle, setup, op)
                and known_refs(refs)
                and all(ref in mapping for ref in refs)
            ):
                unsupported.update(mapping[ref] for ref in refs)
            else:
                debt = True
        else:
            # A rotary claim names faces its window merely intersects: the union decides.
            (rotary if approach(bundle, setup, op) == ROTARY else claimed).update(indices)
    refs = record(bundle.plan.get("stock")).get("as_is_faces", "unknown")
    mapping, invalid = record(facts.get("mapping")), record(facts.get("mapping_errors"))
    # A profiled blank's as-is face counts only once supplied as cut within its bands; a
    # refused one is listed in ``as_is_withheld`` (blank_credit's row prints why).
    credits = blank_credit.credit(bundle, facts)
    withheld = []
    if credits:
        cite.append("blank_credit: profiled-blank as-is faces on the blank and within bands")
    if isinstance(refs, list):
        for ref in refs:
            verdict = record(credits.get(ref)).get("verdict", blank_credit.CREDITED)
            if ref == "unknown":
                debt = True
            elif ref in invalid:
                errors.append(ref)
            elif ref not in mapping:
                debt = True
            elif verdict == blank_credit.CREDITED:
                claimed.add(mapping[ref])
            elif verdict == "unknown":
                debt = True
            else:
                withheld.append(ref)
    else:
        debt = True
    formed, formed_debts, pending, formed_rows = joint_formed(bundle, facts)
    claimed |= formed
    if formed_rows:
        cite.append(
            "plan.setups.<id>.joint.forms: joined corner admitted by the kernel and checked"
        )
    # Whole-face claims and as-stock supersede any rotary portion of the same face.
    complete, gaps, unresolved = rotary_union(facts, "cut", rotary - claimed)
    claimed |= complete
    if rotary:
        cite.append("kernel rotary_coverage.cut: exact union of rotary window portions per face")
    # A formed feature's faces whose credit is debt are judged by that debt, not as missing.
    unclaimed = sorted(all_faces - claimed - set(gaps) - set(unresolved) - pending)
    values = {
        "face_count": len(all_faces),
        "claimed_face_count": len(all_faces & claimed),
        "unclaimed_faces": [face.get("ref") for face in faces if face["index"] in unclaimed],
        "unclaimed_indices": unclaimed,
    }
    if gaps:
        values["rotary_gaps"] = list(gaps.values())
    if unresolved:
        values["rotary_unresolved"] = list(unresolved.values())
    if withheld:
        values["as_is_withheld"] = withheld
    if formed_rows:
        values["joint_formed"] = formed_rows
    uncovered = set(unclaimed) | set(gaps)
    if errors:
        values["mapping_errors"] = sorted(set(errors))
        status, message = (
            "error",
            "invalid STEP face reference(s): " + ", ".join(values["mapping_errors"]),
        )
    elif debt or formed_debts and not uncovered:
        status, message = (
            "unknown",
            "; ".join(([CLAIM_DEBT] if debt else []) + formed_debts),
        )
    elif unresolved:
        status, message = (
            "unknown",
            "rotary window coverage is unresolved for "
            + "; ".join(map(rotary_debt_text, unresolved.values())),
        )
    elif uncovered and uncovered <= unsupported:
        status, message = "unsupported", LATHE_APPROACH_REASON
    elif uncovered:
        # A mixed error names only truly missing claims and gaps, not unsupported candidates.
        candidates = uncovered & unsupported
        if candidates:
            unclaimed = sorted(set(unclaimed) - unsupported)
            gaps = {index: gap for index, gap in gaps.items() if index not in unsupported}
            values.update(
                unclaimed_faces=[face.get("ref") for face in faces if face["index"] in unclaimed],
                unclaimed_indices=unclaimed,
                unsupported_faces=[
                    face.get("ref") for face in faces if face["index"] in candidates
                ],
                unsupported_indices=sorted(candidates),
            )
            values.pop("rotary_gaps", None)
            if gaps:
                values["rotary_gaps"] = list(gaps.values())
        problems = []
        if unclaimed:
            names = [
                face.get("ref") or f"imported face index {face['index']}"
                for face in faces
                if face["index"] in unclaimed
            ]
            problems.append("faces have no cutting op or as-stock claim: " + ", ".join(names))
        if gaps:
            problems.append(
                "rotary windows leave part of a claimed face uncut: "
                + "; ".join(map(rotary_gap_text, gaps.values()))
            )
        status, message = "error", "; ".join(problems)
    else:
        status, message = (
            "pass",
            "every imported face is claimed by a cutting op, declared as-stock or formed by "
            "a checked joint"
            if formed
            else "every imported face is claimed by a cutting op or declared as-stock",
        )
    return [Finding("coverage", subject, status, values, cite, f"{subject}: {message}.")]
