"""Shared geometry debt/provenance boundaries; no host-side geometric guesses."""

from prechips.findings import Finding
from prechips.rules.datum_consistency import _cuts
from prechips.rules.resolution import (
    COMPLETE_FORM,
    MANUAL,
    SAW_OPS,
    WORKHOLDING_CATEGORIES,
    _citations,
    claim_refs,
    inventory_category,
    known_refs,
    number,
    op_feature,
    operations,
    plan_frame_cite,
    record,
    resolve,
    setup_frame,
)
from prechips.rules.turned_profile import PROFILE_OPS

UNKNOWN = "unknown"
_NONCUTTING = MANUAL | {"transfer"}
LATHE_APPROACH_REASON = (
    "turning action has no approach model off a lathe "
    "(the turning model needs a lathe spindle on setup Z)"
)
TURNING = "turning"
ROTARY = "rotary"
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
SAW_TOOL_MODEL_REASON = (
    "a saw cut is located by its cut_plane and blade kerf; this axial/turning tool-cylinder "
    "check does not model a saw blade"
)


def blade_keys(inputs):
    """A two-cornered blade op's extra turning inputs (job ``corners == 2``), else none."""
    return TURNING_BLADE_KEYS if inputs.get("corners") == 2 else ()


def approach(bundle, setup, op):
    """'turning', 'rotary' (dividing-head milling), 'axial' (-Z cutter cylinders) or None
    when no approach model applies."""
    machine = record(resolve(bundle, "machines", setup.get("machine")))
    kind, action = machine.get("kind"), op.get("do")
    if op.get("approach") == ROTARY and kind != "lathe" and action not in _TURNING_ACTIONS:
        # The engine checks the hold: a horizontal dividing-head axis, else unsupported.
        return ROTARY
    if kind == "lathe":
        return "axial" if action in _AXIAL_LATHE_ACTIONS else TURNING
    if action in _TURNING_ACTIONS or (kind != "mill" and action in PROFILE_OPS):
        return None
    return "axial"


def approach_model_reason(bundle, setup, op):
    """Name the unsupported domain before consuming any engine approach facts."""
    return LATHE_APPROACH_REASON if approach(bundle, setup, op) is None else None


def approach_facts(bundle, facts, setup, op):
    """Whether a turning/rotary op's kernel facts come from its own model (never raw -Z
    facts); axial ops always do."""
    model = approach(bundle, setup, op)
    if model not in (TURNING, ROTARY):
        return True
    detail = record(record(facts.get("ops")).get(f"{setup['id']}:{op['op']}"))
    return detail.get("approach") == model


def cutting_action(op):
    action = op.get("do", UNKNOWN)
    if action == UNKNOWN:
        return None
    return action not in _NONCUTTING


def finishing_subjects(bundle):
    # Reuse the existing final datum-cut semantics, including drill→ream/bore/tap.
    # A saw cut removes stock but never finishes a target face; nor does stock
    # preparation of a plan process feature (it has no drawing face to finish).
    return {
        f"{setup['id']}:{op['op']}"
        for name, definition in bundle.feature_definitions.items()
        if not record(record(definition).get("process"))
        for _, setup, op in _cuts(bundle, name)
        if cutting_action(op) is True and op.get("do") not in SAW_OPS | {"coating"}
    }


def complete_form_subjects(bundle):
    """Each feature's last drill/ream/bore/counterbore in setup then op order.

    That one cut's setup output must leave its claimed hole caps formed. A pilot, a
    counterbore's drill, a spot and a tap never own them; a thread's last drill does.
    """
    owners = {}
    for setup in bundle.plan["setups"]:
        for op in setup["ops"]:
            if op.get("do") in COMPLETE_FORM:
                owners[op.get("feature")] = f"{setup['id']}:{op['op']}"
    return set(owners.values())


def provenance(bundle, rule, setup=None, op=None, feature=None):
    section = "4.3" if rule in {"vise", "thin_wall_under_clamp", "fixture_interference"} else "4.2"
    cite = [f"PLAN.md §{section} {rule}"]
    digest = bundle.features.get("step_sha256", UNKNOWN)
    if digest != UNKNOWN:
        cite.append(f"kernel: STEP SHA-256 {digest}; FreeCAD B-rep measurements")
    if feature is not None:
        entry = record(bundle.feature_definitions.get(feature))
        joint = record(entry.get("joint"))
        if joint:
            cite.append(f"plan.joint_features.{joint['id']}: analytic transient cylinder")
        elif record(entry.get("process")):
            from prechips.process_features import source_cite

            cite.extend(source_cite(entry))
        else:
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
    feature = record(bundle.feature_definitions.get(name))
    if record(feature.get("process")):
        # Stock preparation maps to no finished face: it is never drawing coverage.
        return set(), []
    joint = record(feature.get("joint"))
    refs = [joint["label"]] if joint else feature.get("faces", UNKNOWN)
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


def op_claims(bundle, facts, setup, op):
    """(valid claimed indices or None, far-side refs, invalid refs) from the op's kernel facts.

    For supported operations, only faces that the setup approach can cut are
    credited: milling faces that face -Z, lathe faces of revolution about setup Z;
    others are claim errors; unresolved directions leave the claim unknown. Lathe
    claims credit only turning-model facts, never raw -Z milling verdicts.

    A transient joint-feature op's analytic claims never credit finished faces: it earns
    only the kernel's ``certified_indices``, the exported faces its accepted finishing cut
    measurably leaves as its own surface, and otherwise an empty set (never debt). A plan
    process-feature op (stock preparation) credits no finished face at all.
    """
    refs = claim_refs(bundle, op)
    if record(record(bundle.feature_definitions.get(op_feature(op))).get("process")):
        return set(), [], []
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
    joint = bool(record(record(bundle.feature_definitions.get(op.get("feature"))).get("joint")))
    if approach_model_reason(bundle, setup, op) or not approach_facts(bundle, facts, setup, op):
        return (set() if joint else None), [], []
    away = detail.get("claim_errors")
    away = sorted(ref for ref in away if isinstance(ref, str)) if isinstance(away, list) else []
    if joint:
        return _certified(facts, detail), away, []
    indices = detail.get("claimed_indices", UNKNOWN)
    if not isinstance(indices, list) or not all(
        isinstance(i, int) and not isinstance(i, bool) and i >= 0 for i in indices
    ):
        return None, away, []
    return set(indices), away, []


def _certified(facts, detail):
    """A joint op's certified finished-face indices; any non-STEP index voids them all."""
    indices = detail.get("certified_indices")
    faces = facts.get("faces")
    step = {
        face.get("index")
        for face in (faces if isinstance(faces, list) else [])
        if isinstance(face, dict) and _face_index(face.get("index"))
    }
    if not isinstance(indices, list) or not all(_face_index(i) and i in step for i in indices):
        return set()
    return set(indices)


def _face_index(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _face_rows(rows):
    return [
        row
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and _face_index(row.get("index"))
    ]


def _span(span):
    span = record(span)
    bounds = (span.get("z_mm"), span.get("angle_deg"))
    if not isinstance(span.get("setup"), str) or not all(
        isinstance(pair, list) and len(pair) == 2 and all(number(v) for v in pair)
        for pair in bounds
    ):
        return None
    return {"setup": span["setup"], "z_mm": list(bounds[0]), "angle_deg": list(bounds[1])}


def rotary_union(facts, category, indices):
    """Decide rotary-claimed faces from the kernel's model-frame union of window portions.

    A rotary op's ``claimed_indices`` names every face its window merely intersects, so it
    never credits a whole face by itself. ``rotary_coverage[category]`` (``"cut"``, or
    ``"finish"`` over finishing ops only) decides each of ``indices``. Returns
    ``(complete, gaps, unresolved)``: indices the exact union covers; ``{index: gap}``
    with the uncovered area and its per-setup spans; ``{index: debt}`` where the union is
    unknown or the kernel reported none for that face. Unknown outranks a gap, which
    outranks completion, so a contradictory report never credits a face.
    """
    entry = record(record(facts.get("rotary_coverage")).get(category))
    listed = entry.get("complete_indices")
    covered = {i for i in (listed if isinstance(listed, list) else []) if _face_index(i)}
    gaps = {row["index"]: row for row in _face_rows(entry.get("gaps"))}
    unknown = {row["index"]: row for row in _face_rows(entry.get("unknown"))}
    faces = facts.get("faces")
    names = {
        face.get("index"): face.get("ref")
        for face in (faces if isinstance(faces, list) else [])
        if isinstance(face, dict)
    }
    complete, uncovered, unresolved = set(), {}, {}
    for index in sorted(indices):
        name = names.get(index) or f"imported face index {index}"
        if index in unknown:
            reason = unknown[index].get("reason")
            if not isinstance(reason, str) or not reason:
                reason = "rotary window union is unresolved"
            unresolved[index] = {"index": index, "ref": name, "reason": reason}
        elif index in gaps:
            gap = gaps[index]
            spans = gap.get("spans")
            area = gap.get("area_mm2")
            uncovered[index] = {
                "index": index,
                "ref": name,
                "area_mm2": area if number(area) else UNKNOWN,
                "spans": [
                    span for span in map(_span, spans if isinstance(spans, list) else []) if span
                ],
            }
        elif index in covered:
            complete.add(index)
        else:
            unresolved[index] = {
                "index": index,
                "ref": name,
                "reason": "the kernel reported no rotary window union for it",
            }
    return complete, uncovered, unresolved


def rotary_gap_text(gap):
    """``#5 (12.5 mm² at S1 z 10..20 mm, angle 0..90°)``: the portion of a face outside
    every claiming window; angles may be conservative enclosing bounds of that portion."""
    spans = " and ".join(
        f"{span['setup']} z {span['z_mm'][0]:g}..{span['z_mm'][1]:g} mm, "
        f"angle {span['angle_deg'][0]:g}..{span['angle_deg'][1]:g}°"
        for span in gap["spans"]
    )
    area = f"{gap['area_mm2']:g} mm²" if number(gap["area_mm2"]) else ""
    detail = " at ".join(part for part in (area, spans) if part)
    return f"{gap['ref']} ({detail})" if detail else gap["ref"]


def rotary_debt_text(row):
    return f"{row['ref']} ({row['reason']})"


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
        cite = provenance(bundle, rule, setup, op, op_feature(op))
        if op.get("do") in SAW_OPS:
            # Before kernel availability: the tool-cylinder model never applies to a blade.
            yield (
                setup,
                op,
                facts,
                {},
                jobs.get(subject, {}),
                cite,
                Finding(
                    rule,
                    subject,
                    "not_applicable",
                    {"operation": op["do"]},
                    cite,
                    f"{subject}: {SAW_TOOL_MODEL_REASON}.",
                ),
            )
            continue
        blocked = unavailable(bundle, rule, subject, facts, cite)
        inputs = jobs.get(subject, {})
        approach_reason = approach_model_reason(bundle, setup, op)
        model = approach(bundle, setup, op)
        turned = model == TURNING
        keys = (*turning, *blade_keys(inputs)) if turned and turning is not None else required
        # Raw -Z collision/stock/corner facts never establish turning or rotary results.
        stale = not approach_facts(bundle, facts, setup, op)
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
                if detail.get("joint_error"):
                    blocked = Finding(
                        rule,
                        subject,
                        "error",
                        {},
                        cite,
                        f"{subject}: {detail['joint_error']}.",
                    )
                elif invalid:
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
                        f"{subject}: kernel facts for this lathe op are not turning-model facts."
                        if turned
                        else f"{subject}: kernel facts for this rotary op are not rotary-model "
                        "facts.",
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
                elif away and model == ROTARY:
                    blocked = Finding(
                        rule,
                        subject,
                        "error",
                        {"claim_errors": away},
                        cite,
                        f"{subject}: claimed face(s) are not external surfaces of revolution "
                        "about the dividing-head axis inside the op's rotary window: "
                        f"{', '.join(away)}.",
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
        unloaded = rule == "thin_wall_under_clamp" and unclamped_noncutting(setup, inputs)
        if blocked is None:
            if detail.get("assembly_error"):
                blocked = Finding(
                    rule,
                    subject,
                    "error",
                    {},
                    cite,
                    f"{subject}: {detail['assembly_error']}.",
                )
            elif inputs["kind"] == UNKNOWN:
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
                        or unloaded
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
            elif unloaded and detail:
                blocked = Finding(
                    rule,
                    subject,
                    "not_applicable",
                    {},
                    cite,
                    f"{subject}: every operation is non-cutting and the {inputs['kind']} hold "
                    "declares no clamp, so no wall is under clamping load.",
                )
        yield setup, facts, detail, inputs, cite, blocked


def strap_clamped(inputs):
    """A posed-solids hold that declares clamps (drawn or with named clamp debts)."""
    return "solids" in inputs and bool(inputs.get("clamps") or inputs.get("clamp_debts"))


def unclamped_noncutting(setup, inputs):
    """Explicitly clamp-free posed support under known non-cutting actions."""
    hold = record(setup.get("hold"))
    return (
        "solids" in inputs
        and inputs["kind"] not in CHUCK_KINDS
        and inputs["kind"] not in ("vise", "dividing_head")
        and not strap_clamped(inputs)
        and hold.get("clamp") in ("none", "not_applicable")
        and hold.get("clamps", []) == []
        and bool(setup["ops"])
        and all(cutting_action(op) is False for op in setup["ops"])
    )


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
