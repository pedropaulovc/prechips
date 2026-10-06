"""Every finish requirement's face set must be touched by finishing cuts.

A claimed hole cap is credited only once its complete-form cut's setup output is
measured clear of it (the engine's ``cap_completion``): a touched cap is an error and
an unmeasured one is unknown, whether or not a later setup consumes that stock.
"""

from prechips.findings import Finding
from prechips.rules.geometry_common import (
    LATHE_APPROACH_REASON,
    approach_model_reason,
    cutting_action,
    finishing_subjects,
    mapped_feature,
    op_claims,
    provenance,
    unavailable,
)
from prechips.rules.resolution import SAW_OPS, claim_refs, known_refs, operations, record


def evaluate(bundle):
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    finishers = finishing_subjects(bundle)
    claimed, invalid_refs, debt = set(), [], False
    unsupported = set()
    unformed, pending = set(), {}  # cap index -> why its formation is unknown
    mapping, op_facts = record(facts.get("mapping")), record(facts.get("ops"))
    for setup, op in operations(bundle):
        if record(record(bundle.feature_definitions.get(op.get("feature"))).get("joint")):
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
                pending.update(dict.fromkeys(caps, str(completion.get("reason", "unknown"))))
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
            claimed.update(indices)
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
                credited = claimed - unformed - pending.keys()
                missing = sorted(indices - credited)
                values.update(required_faces=sorted(indices), uncovered_faces=missing)
                if missing and set(missing) <= unsupported:
                    status, message = "unsupported", LATHE_APPROACH_REASON
                else:
                    # Keep unsupported-only rows intact; partition a mixed error's faces.
                    candidates = set(missing) & unsupported
                    if candidates:
                        missing = sorted(set(missing) - unsupported)
                        values.update(uncovered_faces=missing, unsupported_faces=sorted(candidates))
                    formless = sorted(set(missing) & unformed)
                    if formless:
                        values["unformed_caps"] = formless
                    waiting = sorted(set(missing) & pending.keys() - unformed)
                    if set(missing) - set(waiting):
                        status = "error"
                        message = (
                            "finish-required hole cap(s) still touch stock after their "
                            "complete-form cut's setup"
                            if formless
                            else "finish-required faces lack a finishing cut"
                        )
                    elif waiting:
                        status = "unknown"
                        message = "hole cap completion is unknown: " + "; ".join(
                            sorted({pending[index] for index in waiting})
                        )
                    else:
                        status = "pass"
                        message = "every finish-required face is claimed by a finishing cut"
        rows.append(Finding("finish_coverage", name, status, values, cite, f"{name}: {message}."))
    return rows
