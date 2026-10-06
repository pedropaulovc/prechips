"""Every finish requirement's face set must be touched by finishing cuts.

A claimed hole cap is credited only once its complete-form cut's setup output is
measured clear of it (the engine's ``cap_completion``): a touched cap is an error and
an unmeasured one is unknown, whether or not a later setup consumes that stock.
"""

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    LATHE_APPROACH_REASON,
    ROTARY,
    approach,
    approach_model_reason,
    cutting_action,
    finishing_subjects,
    mapped_feature,
    op_claims,
    provenance,
    rotary_debt_text,
    rotary_gap_text,
    rotary_union,
    unavailable,
)
from prechips.rules.resolution import (
    SAW_OPS,
    claim_refs,
    known_refs,
    op_feature,
    operations,
    record,
)


def evaluate(bundle):
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    finishers = finishing_subjects(bundle)
    claimed, rotary, invalid_refs, debt = set(), set(), [], False
    unsupported = set()
    unformed, cap_pending = set(), {}  # cap index -> why its formation is unknown
    mapping, op_facts = record(facts.get("mapping")), record(facts.get("ops"))
    for setup, op in operations(bundle):
        if record(record(bundle.feature_definitions.get(op_feature(op))).get("joint")):
            continue
        if op.get("do") in SAW_OPS:
            # A saw cut is never a finishing claim on a target face.
            continue
        subject = f"{setup['id']}:{op['op']}"
        if cutting_action(op) is None:
            debt = True
        # A thread's tap drill owns its caps but is no finisher once the tap follows.
        completion = record(record(op_facts.get(subject)).get("cap_completion"))
        caps = completion.get("caps")
        if isinstance(caps, list):
            if isinstance(completion.get("unformed"), list):
                unformed.update(completion["unformed"])
            else:
                cap_pending.update(dict.fromkeys(caps, str(completion.get("reason", "unknown"))))
        if subject not in finishers:
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
                credited = claimed - unformed - cap_pending.keys()
                missing = indices - credited
                partial = {index: gaps[index] for index in sorted(missing) if index in gaps}
                rotary_pending = [
                    unresolved[index] for index in sorted(missing) if index in unresolved
                ]
                uncovered = sorted(
                    missing - set(partial) - {row["index"] for row in rotary_pending}
                )
                values.update(required_faces=sorted(indices), uncovered_faces=uncovered)
                if rotary & indices:
                    cite = cite + [
                        "kernel rotary_coverage.finish: exact union of finishing rotary "
                        "window portions per face"
                    ]
                if partial:
                    values["rotary_gaps"] = list(partial.values())
                if rotary_pending:
                    values["rotary_unresolved"] = rotary_pending
                    status, message = (
                        "unknown",
                        "rotary finishing window coverage is unresolved for "
                        + "; ".join(map(rotary_debt_text, rotary_pending)),
                    )
                elif missing and missing <= unsupported:
                    status, message = "unsupported", LATHE_APPROACH_REASON
                else:
                    # Keep unsupported-only rows intact; partition a mixed error's faces.
                    candidates = missing & unsupported
                    if candidates:
                        missing -= unsupported
                        uncovered = sorted(set(uncovered) - unsupported)
                        partial = {i: gap for i, gap in partial.items() if i not in unsupported}
                        values.update(
                            uncovered_faces=uncovered, unsupported_faces=sorted(candidates)
                        )
                        values.pop("rotary_gaps", None)
                        if partial:
                            values["rotary_gaps"] = list(partial.values())
                    formless = missing & unformed
                    if formless:
                        values["unformed_caps"] = sorted(formless)
                    waiting = missing & cap_pending.keys() - unformed
                    problems = []
                    if formless:
                        problems.append(
                            "finish-required hole cap(s) still touch stock after their "
                            "complete-form cut's setup"
                        )
                    if set(uncovered) - waiting - formless:
                        problems.append("finish-required faces lack a finishing cut")
                    if partial:
                        problems.append(
                            "rotary finishing windows leave part of a finish-required face "
                            "unfinished: " + "; ".join(map(rotary_gap_text, partial.values()))
                        )
                    if problems:
                        status, message = "error", "; ".join(problems)
                    elif waiting:
                        status = "unknown"
                        message = "hole cap completion is unknown: " + "; ".join(
                            sorted({cap_pending[index] for index in waiting})
                        )
                    else:
                        status, message = (
                            "pass",
                            "every finish-required face is claimed by a finishing cut",
                        )
        rows.append(Finding("finish_coverage", name, status, values, cite, f"{name}: {message}."))
    return rows
