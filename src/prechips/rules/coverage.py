"""All imported faces need a cutting claim or explicit as-stock declaration."""

from prechips.findings import Finding
from prechips.rules.geometry_common import cutting_action, op_claims, provenance, unavailable
from prechips.rules.resolution import operations, record


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
    claimed, errors, debt = set(), [], False
    for setup, op in operations(bundle):
        action = cutting_action(op)
        if action is False:
            continue
        if action is None:
            debt = True
            continue
        # Faces an op names but which point away from its setup are never credited.
        indices, _, invalid = op_claims(bundle, facts, setup, op)
        errors.extend(invalid)
        if indices is None:
            debt = True
        else:
            claimed.update(indices)
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
    unclaimed = sorted(all_faces - claimed)
    values = {
        "face_count": len(all_faces),
        "claimed_face_count": len(all_faces & claimed),
        "unclaimed_faces": [face.get("ref") for face in faces if face["index"] in unclaimed],
        "unclaimed_indices": unclaimed,
    }
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
    elif unclaimed:
        names = [
            face.get("ref") or f"imported face index {face['index']}"
            for face in faces
            if face["index"] in unclaimed
        ]
        status, message = "error", "faces have no cutting op or as-stock claim: " + ", ".join(names)
    else:
        status, message = (
            "pass",
            "every imported face is claimed by a cutting op or declared as-stock",
        )
    return [Finding("coverage", subject, status, values, cite, f"{subject}: {message}.")]
