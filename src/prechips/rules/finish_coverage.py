"""Every finish requirement's face set must be touched by finishing cuts."""

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    LATHE_APPROACH_REASON,
    ROTARY,
    approach,
    approach_model_reason,
    claim_refs,
    cutting_action,
    finishing_subjects,
    known_refs,
    mapped_feature,
    op_claims,
    provenance,
    rotary_debt_text,
    rotary_gap_text,
    rotary_union,
    unavailable,
)
from prechips.rules.resolution import SAW_OPS, operations, record


def evaluate(bundle):
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    finishers = finishing_subjects(bundle)
    claimed, rotary, invalid_refs, debt = set(), set(), [], False
    unsupported = set()
    mapping = record(facts.get("mapping"))
    for setup, op in operations(bundle):
        if op.get("do") in SAW_OPS:
            # A saw cut is never a finishing claim on a target face.
            continue
        if cutting_action(op) is None:
            debt = True
        if f"{setup['id']}:{op['op']}" not in finishers:
            continue
        # Milling finish cuts credit reachable faces; lathe claims name only candidates.
        indices, _, invalid = op_claims(bundle, facts, setup, op)
        invalid_refs.extend(invalid)
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
            # A rotary finishing claim names faces its window merely intersects; only the
            # finishing ops' window union finishes a face, and as-stock never does.
            (rotary if approach(bundle, setup, op) == ROTARY else claimed).update(indices)
    complete, gaps, unresolved = rotary_union(facts, "finish", rotary - claimed)
    claimed |= complete
    rows = []
    for name, feature in bundle.features["features"].items():
        cite = provenance(bundle, "finish_coverage", feature=name)
        blocked = unavailable(bundle, "finish_coverage", name, facts, cite)
        if blocked:
            rows.append(blocked)
            continue
        requirements = feature.get("requirements", "unknown")
        values = {"finish_ra": feature.get("finish_ra", "unknown")}
        if (
            isinstance(requirements, list)
            and "finish_ra" not in requirements
            and "finish_ra" not in feature
        ):
            status, message = "not_applicable", "drawing declares no finish requirement"
        elif "finish_ra" not in feature or feature.get("finish_ra") == "unknown":
            status, message = "unknown", "finish requirement identity or Ra value is unknown"
        else:
            indices, invalid = mapped_feature(bundle, facts, name)
            invalid = sorted(set(invalid + invalid_refs))
            if invalid:
                values["mapping_errors"] = invalid
                status, message = "error", "invalid STEP face reference(s): " + ", ".join(invalid)
            elif indices is None or debt:
                status, message = (
                    "unknown",
                    "finish face references or finishing operation claims are unresolved",
                )
            else:
                missing = indices - claimed
                partial = {index: gaps[index] for index in sorted(missing) if index in gaps}
                pending = [unresolved[index] for index in sorted(missing) if index in unresolved]
                uncovered = sorted(missing - set(partial) - {row["index"] for row in pending})
                values.update(required_faces=sorted(indices), uncovered_faces=uncovered)
                if rotary & indices:
                    cite = cite + [
                        "kernel rotary_coverage.finish: exact union of finishing rotary "
                        "window portions per face"
                    ]
                if partial:
                    values["rotary_gaps"] = list(partial.values())
                if pending:
                    values["rotary_unresolved"] = pending
                    status, message = (
                        "unknown",
                        "rotary finishing window coverage is unresolved for "
                        + "; ".join(map(rotary_debt_text, pending)),
                    )
                elif missing and missing <= unsupported:
                    status, message = "unsupported", LATHE_APPROACH_REASON
                else:
                    # Keep unsupported-only rows intact; partition a mixed error's faces.
                    candidates = missing & unsupported
                    if candidates:
                        uncovered = sorted(set(uncovered) - unsupported)
                        partial = {i: gap for i, gap in partial.items() if i not in unsupported}
                        values.update(
                            uncovered_faces=uncovered, unsupported_faces=sorted(candidates)
                        )
                        values.pop("rotary_gaps", None)
                        if partial:
                            values["rotary_gaps"] = list(partial.values())
                    problems = ["finish-required faces lack a finishing cut"] if uncovered else []
                    if partial:
                        problems.append(
                            "rotary finishing windows leave part of a finish-required face "
                            "unfinished: " + "; ".join(map(rotary_gap_text, partial.values()))
                        )
                    status = "error" if problems else "pass"
                    message = (
                        "; ".join(problems)
                        if problems
                        else "every finish-required face is claimed by a finishing cut"
                    )
        rows.append(Finding("finish_coverage", name, status, values, cite, f"{name}: {message}."))
    return rows
