"""Shared geometry debt/provenance boundaries; no host-side geometric guesses."""

from prechips.findings import Finding
from prechips.rules.datum_consistency import _cuts
from prechips.rules.resolution import (
    MANUAL,
    WORKHOLDING_CATEGORIES,
    _citations,
    inventory_category,
    number,
    operations,
    plan_frame_cite,
    record,
    resolve,
    setup_frame,
)
from prechips.rules.turned_profile import PROFILE_OPS

UNKNOWN = "unknown"
_NONCUTTING = MANUAL | {"fit_up", "transfer"}
LATHE_APPROACH_REASON = (
    "turning action has no approach model off a lathe "
    "(the turning model needs a lathe spindle on setup Z)"
)
TURNING = "turning"
CHUCK_KINDS = {"chuck_3jaw", "chuck_4jaw"}
# Shared profile/form/groove actions also occur on mills; resolve their machine kind.
_TURNING_ACTIONS = (
    PROFILE_OPS - {"profile", "form", "groove", "rough_groove", "finish_groove"}
) | {"part_off", "cut_to_fit"}
# On a lathe these tools sit on the spindle axis (tailstock): the -Z cylinder model applies.
_AXIAL_LATHE_ACTIONS = {"spot", "drill", "ream", "tap", "center", "center_drill"}
# Turning-model inputs; every one must be known before the engine places a tool.
TURNING_TOOL_KEYS = (
    "radius_mm",
    "insert_angle_deg",
    "entering_angle_deg",
    "feed_z",
    "edge_len_mm",
    "head_len_mm",
    "shank_width_mm",
    "functional_width_mm",
    "projection_mm",
)
TURNING_HOLDER_KEYS = ("holder_body_width_mm", "holder_body_depth_mm")
# Two-cornered grooving/parting blades, by tool ``kind``: the job marks them ``corners = 2``
# and they also need the front-edge width.
TURNING_BLADE_KINDS = frozenset({"parting_blade", "grooving_blade"})
TURNING_BLADE_KEYS = ("blade_width_mm",)


def blade_keys(inputs):
    """A two-cornered blade op's extra turning inputs (job ``corners == 2``), else none."""
    return TURNING_BLADE_KEYS if inputs.get("corners") == 2 else ()


def approach(bundle, setup, op):
    """'turning', 'axial' (-Z cutter cylinders) or None when no approach model applies."""
    machine = record(resolve(bundle, "machines", setup.get("machine")))
    kind, action = machine.get("kind"), op.get("do")
    if kind == "lathe":
        return "axial" if action in _AXIAL_LATHE_ACTIONS else TURNING
    if action in _TURNING_ACTIONS or (kind != "mill" and action in PROFILE_OPS):
        return None
    return "axial"


def approach_model_reason(bundle, setup, op):
    """Name the unsupported domain before consuming any engine approach facts."""
    return LATHE_APPROACH_REASON if approach(bundle, setup, op) is None else None


def turning_facts(bundle, facts, setup, op):
    """Whether a lathe op's kernel facts come from the turning model, never raw -Z facts."""
    detail = record(record(facts.get("ops")).get(f"{setup['id']}:{op['op']}"))
    return detail.get("approach") == TURNING


def cutting_action(op):
    action = op.get("do", UNKNOWN)
    if action == UNKNOWN:
        return None
    return action not in _NONCUTTING


def finishing_subjects(bundle):
    # Reuse the existing final datum-cut semantics, including drill→ream/bore/tap.
    return {
        f"{setup['id']}:{op['op']}"
        for name in bundle.features["features"]
        for _, setup, op in _cuts(bundle.plan["setups"], name)
        if cutting_action(op) is True and op.get("do") != "coating"
    }


def provenance(bundle, rule, setup=None, op=None, feature=None):
    section = "4.3" if rule in {"vise", "thin_wall_under_clamp", "fixture_interference"} else "4.2"
    cite = [f"PLAN.md §{section} {rule}"]
    digest = bundle.features.get("step_sha256", UNKNOWN)
    if digest != UNKNOWN:
        cite.append(f"kernel: STEP SHA-256 {digest}; FreeCAD B-rep measurements")
    if feature is not None:
        entry = record(bundle.features["features"].get(feature))
        cite.append(f"features.{feature}: faces and requirements")
        cite.extend(_citations(entry.get("cite")))
    if setup is not None:
        cite.append(f"plan.setups.{setup['id']}: frame and hold")
        hold = record(setup.get("hold"))
        fixture_category = inventory_category(bundle, hold.get("fixture"), WORKHOLDING_CATEGORIES)
        for category, reference in (
            (fixture_category, hold.get("fixture")),
            ("fixtures", hold.get("parallels")),
        ):
            item = record(resolve(bundle, category, reference)) if category else {}
            if item:
                cite.append(f"inventory.{category}.{reference}: declared dimensions")
                cite.extend(_citations(item.get("cite")))
                cite.extend(_citations(record(item.get("source")).get("cite")))
                cite.extend(
                    _citations(item.get("source")) if isinstance(item.get("source"), str) else []
                )
        # Exported frames keep their own cites; a plan-owned frame names its owner too.
        cite.extend(
            plan_frame_cite(bundle, setup) or _citations(setup_frame(bundle, setup).get("cite"))
        )
    if op is not None:
        cite.append(f"plan.setups.{setup['id']}.ops.{op['op']}: selected action/tool/holder")
        for category, reference in (("tools", op.get("tool")), ("holders", op.get("holder"))):
            item = record(resolve(bundle, category, reference))
            if item:
                cite.append(f"inventory.{category}.{reference}: explicit-unit verified dimensions")
                cite.extend(_citations(item.get("cite")))
                cite.extend(_citations(item.get("dia_cite")))
                cite.extend(_citations(record(item.get("source")).get("cite")))
    return list(dict.fromkeys(cite))


def unavailable(bundle, rule, subject, facts, cite):
    status = facts.get("status")
    if status == "ok":
        return None
    numbers = {"kernel_status": status or UNKNOWN}
    if facts.get("kernel_unavailable") is True:
        numbers["kernel_unavailable"] = True
    return Finding(
        rule,
        subject,
        "error" if status == "error" else "unknown",
        numbers,
        cite,
        facts.get("reason", "FreeCAD geometry facts are unavailable."),
    )


def mapped_feature(bundle, facts, name):
    feature = record(bundle.features["features"].get(name))
    refs = feature.get("faces", UNKNOWN)
    errors = record(facts.get("mapping_errors"))
    if isinstance(refs, list):
        invalid = [ref for ref in refs if ref != UNKNOWN and ref in errors]
        if invalid:
            return None, invalid
    indices = record(facts.get("features")).get(name, UNKNOWN)
    if (
        not isinstance(refs, list)
        or not refs
        or UNKNOWN in refs
        or not isinstance(indices, list)
        or not indices
    ):
        return None, []
    if len(indices) != len(set(indices)) or not all(
        isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in indices
    ):
        return None, []
    return set(indices), []


def claim_refs(bundle, op):
    """The face refs an op claims: its explicit ``faces``, else its feature's ``faces``."""
    if "faces" in op:
        return op["faces"]
    return record(bundle.features["features"].get(op.get("feature"))).get("faces", UNKNOWN)


def known_refs(refs):
    return isinstance(refs, list) and bool(refs) and UNKNOWN not in refs


def op_claims(bundle, facts, setup, op):
    """(valid claimed indices or None, far-side refs, invalid refs) from the op's kernel facts.

    For supported operations, only faces that the setup approach can cut are
    credited: milling faces that face -Z, lathe faces of revolution about setup Z;
    others are claim errors; unresolved directions leave the claim unknown. Lathe
    claims credit only turning-model facts, never raw -Z milling verdicts.
    """
    refs = claim_refs(bundle, op)
    errors = record(facts.get("mapping_errors"))
    detail = record(record(facts.get("ops")).get(f"{setup['id']}:{op['op']}"))
    reported = detail.get("mapping_errors")
    named = [ref for ref in (refs if isinstance(refs, list) else []) if ref != UNKNOWN]
    invalid = sorted(
        {ref for ref in named if ref in errors}
        | {ref for ref in (reported if isinstance(reported, list) else []) if ref != UNKNOWN}
    )
    if invalid or not known_refs(refs):
        return None, [], invalid
    if approach_model_reason(bundle, setup, op):
        return None, [], []
    if approach(bundle, setup, op) == TURNING and not turning_facts(bundle, facts, setup, op):
        return None, [], []
    away = detail.get("claim_errors")
    away = sorted(ref for ref in away if isinstance(ref, str)) if isinstance(away, list) else []
    indices = detail.get("claimed_indices", UNKNOWN)
    if not isinstance(indices, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in indices
    ):
        return None, away, []
    return set(indices), away, []


def op_contexts(bundle, rule, required=(), fixture=False, stock=True, turning=None):
    """Per-op context; ``turning`` names the required inputs of turning-model ops."""
    from prechips.kernel import build_job, run_geometry

    facts = run_geometry(bundle)
    job = build_job(bundle)
    jobs = {op["subject"]: op for setup in job["setups"] for op in setup["ops"]}
    holds = {setup["id"]: setup["hold"] for setup in job["setups"]}
    frames = {setup["id"]: setup["frame"] for setup in job["setups"]}
    for setup, op in operations(bundle):
        subject = f"{setup['id']}:{op['op']}"
        cite = provenance(bundle, rule, setup, op, op.get("feature"))
        blocked = unavailable(bundle, rule, subject, facts, cite)
        inputs = jobs.get(subject, {})
        approach_reason = approach_model_reason(bundle, setup, op)
        turned = approach(bundle, setup, op) == TURNING
        keys = (*turning, *blade_keys(inputs)) if turned and turning is not None else required
        # Raw -Z collision/stock/corner facts never establish lathe results.
        stale = turned and not turning_facts(bundle, facts, setup, op)
        detail = {} if approach_reason or stale else record(record(facts.get("ops")).get(subject))
        if blocked is None:
            if cutting_action(op) is False:
                blocked = Finding(
                    rule,
                    subject,
                    "not_applicable",
                    {},
                    cite,
                    f"{subject}: {op['do']} does not cut geometry.",
                )
            elif cutting_action(op) is None:
                blocked = Finding(
                    rule, subject, "unknown", {}, cite, f"{subject}: cutting action is unknown."
                )
            else:
                _, away, invalid = op_claims(bundle, facts, setup, op)
                if invalid:
                    blocked = Finding(
                        rule,
                        subject,
                        "error",
                        {"mapping_errors": invalid},
                        cite,
                        f"{subject}: invalid STEP face reference(s): {', '.join(invalid)}.",
                    )
                elif not known_refs(claim_refs(bundle, op)) or (
                    approach_reason
                    and any(
                        ref not in record(facts.get("mapping")) for ref in claim_refs(bundle, op)
                    )
                ):
                    blocked = Finding(
                        rule,
                        subject,
                        "unknown",
                        {},
                        cite,
                        f"{subject}: claimed face references are unknown or unmapped.",
                    )
                elif approach_reason:
                    blocked = Finding(
                        rule,
                        subject,
                        "unsupported",
                        {},
                        cite,
                        f"{subject}: {approach_reason}.",
                    )
                elif frames[setup["id"]] == UNKNOWN:
                    blocked = Finding(
                        rule,
                        subject,
                        "unknown",
                        {},
                        cite,
                        f"{subject}: numeric setup frame is unknown.",
                    )
                elif stale:
                    blocked = Finding(
                        rule,
                        subject,
                        "unknown",
                        {},
                        cite,
                        f"{subject}: kernel facts for this lathe op are not turning-model facts.",
                    )
                elif away and turned:
                    blocked = Finding(
                        rule,
                        subject,
                        "error",
                        {"claim_errors": away},
                        cite,
                        f"{subject}: claimed face(s) are not surfaces of revolution about the "
                        f"spindle axis (setup Z) and cannot be turned: {', '.join(away)}.",
                    )
                elif away:
                    blocked = Finding(
                        rule,
                        subject,
                        "error",
                        {"claim_errors": away},
                        cite,
                        f"{subject}: claimed face(s) point away from the setup approach and "
                        f"cannot be cut from it: {', '.join(away)}.",
                    )
                elif detail.get("unsupported_reason"):
                    blocked = Finding(
                        rule,
                        subject,
                        "unsupported",
                        {},
                        cite,
                        f"{subject}: {detail['unsupported_reason']}.",
                    )
                elif detail.get("stock_removal_error"):
                    blocked = Finding(
                        rule,
                        subject,
                        "error",
                        {},
                        cite,
                        f"{subject}: {detail['stock_removal_error']}.",
                    )
                elif stock and detail.get("stock_reason"):
                    blocked = Finding(
                        rule,
                        subject,
                        "unknown",
                        {},
                        cite,
                        f"{subject}: in-process stock unknown: {detail['stock_reason']}.",
                    )
                elif fixture and holds[setup["id"]].get("reason"):
                    blocked = Finding(
                        rule, subject, "unknown", {}, cite, holds[setup["id"]]["reason"]
                    )
                elif any(not number(inputs.get(key)) for key in keys):
                    blocked = Finding(
                        rule,
                        subject,
                        "unknown",
                        {},
                        cite,
                        f"{subject}: selected tool/holder dimensions are unmeasured "
                        "or unavailable.",
                    )
        yield setup, op, facts, detail, inputs, cite, blocked


def setup_contexts(bundle, rule):
    from prechips.kernel import build_job, run_geometry

    facts = run_geometry(bundle)
    job = build_job(bundle)
    holds = {s["id"]: s["hold"] for s in job["setups"]}
    frames = {s["id"]: s["frame"] for s in job["setups"]}
    for setup in bundle.plan["setups"]:
        subject = setup["id"]
        cite = provenance(bundle, rule, setup)
        inputs = holds[subject]
        detail = record(record(facts.get("setups")).get(subject))
        blocked = unavailable(bundle, rule, subject, facts, cite)
        if blocked is None:
            if inputs["kind"] == UNKNOWN:
                blocked = Finding(
                    rule, subject, "unknown", {}, cite, f"{subject}: holding identity is unknown."
                )
            elif inputs["kind"] != "vise" and not (
                # Every drawn holding is checked against the work and itself. Chuck jaws
                # (including a dividing head's chuck) and straps also load material runs.
                rule == "fixture_interference"
                or (
                    rule == "thin_wall_under_clamp"
                    and (
                        inputs["kind"] in CHUCK_KINDS
                        or (inputs["kind"] == "dividing_head" and head_chuck(setup))
                        or strap_clamped(inputs)
                    )
                )
            ):
                status = "not_applicable" if rule == "vise" else "unsupported"
                blocked = Finding(
                    rule,
                    subject,
                    status,
                    {},
                    cite,
                    f"{subject}: {rule} has no vise grip-zone facts for {inputs['kind']} holding.",
                )
            elif frames[subject] == UNKNOWN:
                blocked = Finding(
                    rule,
                    subject,
                    "unknown",
                    {},
                    cite,
                    f"{subject}: numeric setup frame is unknown.",
                )
            elif detail.get("stock_reason"):
                blocked = Finding(
                    rule,
                    subject,
                    "unknown",
                    {},
                    cite,
                    f"{subject}: in-process stock unknown: {detail['stock_reason']}.",
                )
            elif inputs.get("reason"):
                blocked = Finding(rule, subject, "unknown", {}, cite, inputs["reason"])
        yield setup, facts, detail, inputs, cite, blocked


def strap_clamped(inputs):
    """A posed-solids hold that declares clamps (drawn or with named clamp debts)."""
    return "solids" in inputs and bool(inputs.get("clamps") or inputs.get("clamp_debts"))


def head_chuck(setup):
    """A dividing-head hold that declares the chuck it carries (``hold.chuck``)."""
    return record(setup.get("hold")).get("chuck") not in (None, "none", "not_applicable")


def fact_reason(detail, fields, fallback):
    reasons = record(detail.get("reasons"))
    relevant = [
        reasons[key] for key in fields if key in reasons and detail.get(key, UNKNOWN) == UNKNOWN
    ]
    if relevant:
        return "; ".join(dict.fromkeys(relevant))
    return fallback if reasons else detail.get("reason", fallback)
