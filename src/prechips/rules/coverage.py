"""All imported faces need a cutting claim or explicit as-stock declaration."""

from prechips.findings import Finding
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
from prechips.rules.resolution import SAW_OPS, claim_refs, known_refs, operations, record


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
        # Transient preparation, even with an explicit face override, never cuts the final STEP.
        if record(record(bundle.feature_definitions.get(op.get("feature"))).get("joint")):
            continue
        if op.get("do") in SAW_OPS:
            # A saw cut removes stock; its kerf face is not credit toward target faces.
            continue
        action = cutting_action(op)
        if action is False:
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
    if isinstance(refs, list):
        for ref in refs:
            if ref == "unknown":
                debt = True
            elif ref in invalid:
                errors.append(ref)
            elif ref in mapping:
                claimed.add(mapping[ref])
            else:
                debt = True
    else:
        debt = True
    # Whole-face claims and as-stock supersede any rotary portion of the same face.
    complete, gaps, unresolved = rotary_union(facts, "cut", rotary - claimed)
    claimed |= complete
    if rotary:
        cite.append("kernel rotary_coverage.cut: exact union of rotary window portions per face")
    unclaimed = sorted(all_faces - claimed - set(gaps) - set(unresolved))
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
    uncovered = set(unclaimed) | set(gaps)
    if errors:
        values["mapping_errors"] = sorted(set(errors))
        status, message = (
            "error",
            "invalid STEP face reference(s): " + ", ".join(values["mapping_errors"]),
        )
    elif debt:
        status, message = (
            "unknown",
            "cutting claims are unknown, unmapped or undecided, or as-stock refs are unknown",
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
            "every imported face is claimed by a cutting op or declared as-stock",
        )
    return [Finding("coverage", subject, status, values, cite, f"{subject}: {message}.")]
