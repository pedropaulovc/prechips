"""Shared geometry debt/provenance boundaries; no host-side geometric guesses."""

import math
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import replace

from prechips.findings import Finding
from prechips.material_routes import setup_lineage
from prechips.rules.datum_consistency import _cuts
from prechips.rules.resolution import (
    COMPLETE_FORM,
    HAND_FED,
    HAND_FINISH,
    HAND_THREAD,
    MANUAL,
    SAW_OPS,
    SLITTING_SAW_MODEL_REASON,
    TAP_OPS,
    UNRESOLVED_SAW_MODEL_REASON,
    _citations,
    claim_refs,
    face_identity_text,
    face_mapping,
    known_refs,
    member_protection_status,
    number,
    op_feature,
    operation_members,
    operations,
    plan_frame_cite,
    record,
    registered_workpieces,
    resolve,
    select,
    setup_frame,
    slitting_saw,
    spindle_saw,
)
from prechips.rules.turned_profile import PROFILE_OPS

UNKNOWN = "unknown"
_NONCUTTING = (MANUAL - HAND_THREAD) | {"transfer"}
LATHE_APPROACH_REASON = (
    "turning action has no approach model off a lathe "
    "(the turning model needs a lathe spindle on setup Z)"
)
TURNING = "turning"
ROTARY = "rotary"
# Hand actions have no spindle cutter. Filing has a bounded removal model; die threading
# remains explicit unknown helical removal, never an axial or turning-cylinder stand-in.
HAND = "hand"
CHUCK_KINDS = {"chuck_3jaw", "chuck_4jaw"}
# Shared profile/form/groove actions also occur on mills; resolve their machine kind.
_TURNING_ACTIONS = (
    PROFILE_OPS - {"profile", "form", "groove", "rough_groove", "finish_groove"}
) | {"part_off", "cut_to_fit"}
# On a lathe these tools sit on the spindle axis (tailstock): the -Z cylinder model applies.
_AXIAL_LATHE_ACTIONS = {"spot", "drill", "ream", "center", "center_drill"} | TAP_OPS
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
    """'hand' (manual material cutting), 'turning', 'rotary' (dividing-head milling),
    'axial' (-Z cutter cylinders) or None when no approach model applies."""
    if op.get("do") in HAND_FINISH | HAND_THREAD:
        return HAND
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
    """Whether a hand/turning/rotary op's kernel facts come from its own model (never raw -Z
    facts); axial ops always do."""
    model = approach(bundle, setup, op)
    if model not in (HAND, TURNING, ROTARY):
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
    # preparation of a plan process feature (it has no drawing face to finish). A file to
    # the line does.
    members = (
        record(bundle.plan.get("workpieces")) if registered_workpieces(bundle) else {None: None}
    )
    return {
        f"{setup['id']}:{op['op']}"
        for member in members
        for name, definition in bundle.feature_definitions.items()
        if not record(record(definition).get("preparation"))
        for _, setup, op in _cuts(bundle, name, workpiece_id=member)
        if (cutting_action(op) is True or op.get("do") in HAND_FINISH)
        and op.get("do") not in SAW_OPS | {"coating"}
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
                members = (
                    operation_members(bundle, setup, op)
                    if registered_workpieces(bundle)
                    else (None,)
                )
                for member in members or ():
                    owners[member, op_feature(op)] = f"{setup['id']}:{op['op']}"
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
        elif record(entry.get("preparation")):
            from prechips.process_features import source_cite

            cite.extend(source_cite(entry))
        else:
            cite.append(f"features.{feature}: faces and requirements")
        cite.extend(_citations(entry.get("cite")))
    if setup is not None:
        cite.append(f"plan.setups.{setup['id']}: frame and hold")
        hold = record(setup.get("hold"))
        for slot, reference in (
            ("workholding", hold.get("fixture")),
            ("fixtures", hold.get("parallels")),
        ):
            category, key, _ = select(bundle, reference, slot)
            item = record(resolve(bundle, slot, reference))
            if item:
                cite.append(f"inventory.{category}.{key}: declared dimensions")
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
        for slot, reference in (("tools", op.get("tool")), ("holders", op.get("holder"))):
            category, key, _ = select(bundle, reference, slot)
            item = record(resolve(bundle, slot, reference))
            if item:
                cite.append(f"inventory.{category}.{key}: explicit-unit verified dimensions")
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


def mapped_feature(bundle, facts, name, workpiece_id=None):
    """Exact required native indices, preserving every registered physical member."""
    feature = record(bundle.feature_definitions.get(name))
    if record(feature.get("preparation")):
        return set(), []
    joint = record(feature.get("joint"))
    refs = [joint["label"]] if joint else feature.get("faces", UNKNOWN)
    errors = record(facts.get("mapping_errors"))
    if isinstance(refs, list):
        invalid = [ref for ref in refs if ref != UNKNOWN and ref in errors]
        if invalid:
            return None, invalid
    if not known_refs(refs):
        return None, []
    if registered_workpieces(bundle):
        members = (
            (workpiece_id,) if workpiece_id is not None else record(bundle.plan.get("workpieces"))
        )
        if not members:
            return None, []
        groups = [
            record(record(facts.get("workpiece_features")).get(member)).get(name, UNKNOWN)
            for member in members
        ]
        mapped = face_mapping(bundle, facts, workpiece_id=workpiece_id)
        if any(
            not isinstance(indices, list)
            or not indices
            or not all(_face_index(index) for index in indices)
            or not all(_face_index(mapped.get((member, ref))) for ref in refs)
            or set(indices) != {mapped.get((member, ref)) for ref in refs}
            for member, indices in zip(members, groups, strict=True)
        ):
            return None, []
        indices = [index for group in groups for index in group]
    else:
        indices = record(facts.get("features")).get(name, UNKNOWN)
    if (
        not isinstance(indices, list)
        or not indices
        or not all(_face_index(index) for index in indices)
        or len(indices) != len(set(indices))
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
    refs = claim_refs(bundle, op, setup)
    if record(record(bundle.feature_definitions.get(op_feature(op))).get("preparation")):
        return set(), [], []
    errors = record(facts.get("mapping_errors"))
    detail = record(record(facts.get("ops")).get(f"{setup['id']}:{op['op']}"))
    reported = detail.get("mapping_errors")
    named = [ref for ref in (refs if isinstance(refs, list) else []) if ref != UNKNOWN]
    invalid = sorted(
        {
            face_identity_text(ref)
            for ref in named
            if ref in errors or isinstance(ref, tuple) and ref[1] in errors
        }
        | {
            face_identity_text(ref)
            for ref in (reported if isinstance(reported, list) else [])
            if ref != UNKNOWN
        }
    )
    if invalid or not known_refs(refs):
        return None, [], invalid
    joint = bool(record(record(bundle.feature_definitions.get(op_feature(op))).get("joint")))
    if approach_model_reason(bundle, setup, op) or not approach_facts(bundle, facts, setup, op):
        return (set() if joint else None), [], []
    away = detail.get("claim_errors")
    away = sorted(ref for ref in away if isinstance(ref, str)) if isinstance(away, list) else []
    if joint:
        return _certified(facts, detail), away, []
    indices = detail.get("claimed_indices", UNKNOWN)
    if not isinstance(indices, list) or not all(_face_index(index) for index in indices):
        return None, away, []
    if registered_workpieces(bundle):
        members = operation_members(bundle, setup, op)
        expected = {
            member: [ref for selected, ref in refs if selected == member]
            for member in members or ()
        }
        mapped = face_mapping(bundle, facts, setup)
        if (
            not members
            or detail.get("workpiece_faces") != expected
            or any(
                member_protection_status(bundle, setup, member, facts) is not True
                for member in members
            )
            or any(ref not in mapped or not _face_index(mapped[ref]) for ref in refs)
            or not set(indices) <= {mapped[ref] for ref in refs}
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


def kernel_measurement_debts(job, setup, op=None, *, fixture=False, stock=False):
    """Current host facts behind this context, including its routed stock ancestry."""
    attachment = job.get("measurement_debts", {})
    debts = {}

    def add(entries):
        debts.update((entry["id"], entry) for entry in entries)

    def upstream():
        # Debts describe producer history, not feature survival or material credit.
        lineage = setup_lineage(job, setup["id"])
        for source in job["setups"]:
            sid = source["id"]
            if sid not in lineage:
                continue
            if sid != setup["id"]:
                add(attachment.get("setups", {}).get(sid, []))
            for cut in source["ops"]:
                if (
                    sid == setup["id"]
                    and op is not None
                    and cut["subject"] == (f"{sid}:{op['op']}")
                ):
                    break
                add(attachment.get("ops", {}).get(cut["subject"], []))

    if op is not None:
        add(attachment.get("ops", {}).get(f"{setup['id']}:{op['op']}", []))
    if fixture:
        add(attachment.get("setups", {}).get(setup["id"], []))
    if stock:
        upstream()
    return [debts[key] for key in sorted(debts)]


def with_measurement_debts(finding, entries):
    """Unknown rows retain exact stable fact IDs and fresh provenance diagnostics."""
    if finding.status != UNKNOWN or not entries:
        return finding
    debts = {entry["id"]: entry for entry in finding.numbers.get("measurements", [])}
    debts.update((entry["id"], entry) for entry in entries)
    ordered = [debts[key] for key in sorted(debts)]
    diagnosis = "; ".join(
        f"{entry['id']} ({entry.get('status', UNKNOWN)}): {entry['reason'].rstrip('.')}"
        if entry.get("reason")
        else f"{entry['id']} ({entry.get('status', UNKNOWN)})"
        for entry in ordered
    )
    return replace(
        finding,
        numbers={**finding.numbers, "measurements": ordered},
        cite=list(dict.fromkeys([*finding.cite, *(c for e in ordered for c in e["cite"])])),
        sentence=f"{finding.sentence.rstrip('.')}. Refused kernel facts: {diagnosis}.",
    )


# A host-only caller that already prepared one bundle's kernel job lends it to the rules
# it then evaluates on that same, unchanged bundle (``tools --measure``).
_LENT_JOB = ContextVar("lent_kernel_job", default=None)


@contextmanager
def lend_job(bundle, job):
    """Within the block, :func:`prepared_job` of ``bundle`` is a copy of ``job``."""
    token = _LENT_JOB.set((bundle, job))
    try:
        yield
    finally:
        _LENT_JOB.reset(token)


# Rows a caller already evaluated on this same, unchanged bundle, by rule name: a later
# rule that reads another rule's rows takes them (:func:`rule_rows`) instead of
# evaluating that rule again (``coordinates`` is seconds on a long contour).
_LENT_ROWS = ContextVar("lent_rule_rows", default=None)


@contextmanager
def lend_rows(bundle, rows):
    """Within the block, :func:`rule_rows` of ``bundle`` reads ``rows`` (``{rule: rows}``),
    which the caller may fill as it evaluates."""
    token = _LENT_ROWS.set((bundle, rows))
    try:
        yield
    finally:
        _LENT_ROWS.reset(token)


def rule_rows(bundle, name, evaluate):
    """Rule ``name``'s rows on ``bundle``: the lent ones (:func:`lend_rows`), else
    ``evaluate(bundle)``."""
    lent = _LENT_ROWS.get()
    if lent is not None and lent[0] is bundle and name in lent[1]:
        return lent[1][name]
    return evaluate(bundle)


def prepared_job(bundle):
    """``bundle``'s kernel job: a lent one (:func:`lend_job`), else freshly built."""
    from prechips.kernel import build_job

    lent = _LENT_JOB.get()
    if lent is not None and lent[0] is bundle:
        return deepcopy(lent[1])
    return build_job(bundle)


def mounted_saw_inputs(bundle, setup, op, job=None):
    """The host-normalized mounted assembly; never resolve its dimensions a second time."""
    if job is None:
        from prechips.kernel import mounted_saw_inputs as normalize

        return normalize(bundle, setup, op)
    subject = f"{setup['id']}:{op['op']}"
    return next(
        (
            record(cut.get("mounted_saw"))
            for stage in job.get("setups", [])
            for cut in stage.get("ops", [])
            if cut.get("subject") == subject
        ),
        {},
    )


def _saw_number(value):
    return number(value) and math.isfinite(value)


def _saw_band(value, *, positive=False):
    return (
        isinstance(value, list)
        and len(value) == 2
        and all(_saw_number(v) for v in value)
        and value[0] <= value[1]
        and (not positive or value[0] > 0)
    )


def _saw_reasons(value):
    if isinstance(value, dict):
        return [f"{key}: {message}" for key, message in value.items() if _citations(message)]
    return _citations(value)


def mounted_saw_assembly_evidence(mounted):
    """Consume the one normalized assembly, preserving known incompatibility before debt."""
    mounted = record(mounted)
    errors = _saw_reasons(mounted.get("assembly_errors", mounted.get("errors")))
    if errors:
        return "error", errors
    reasons = _saw_reasons(mounted.get("assembly_reasons", mounted.get("reasons")))
    blade, arbor = record(mounted.get("blade")), record(mounted.get("arbor"))
    complete = (
        mounted.get("model") == "finite_disk_v1"
        and all(
            _saw_number(blade.get(key))
            for key in (
                "dia_mm",
                "root_dia_mm",
                "thickness_mm",
                "kerf_mm",
                "kerf_offset_mm",
            )
        )
        and all(blade[key] > 0 for key in ("dia_mm", "root_dia_mm", "thickness_mm", "kerf_mm"))
        and _saw_band(blade.get("bore_dia_limits_mm"), positive=True)
        and all(
            _saw_number(arbor.get(key))
            for key in ("projection_mm", "gauge_len_mm", "bore_clearance_max_mm")
        )
        and arbor["projection_mm"] > 0
        and arbor["gauge_len_mm"] >= 0
        and arbor["bore_clearance_max_mm"] >= 0
        and _saw_band(arbor.get("pilot_dia_limits_mm"), positive=True)
        and _saw_band(arbor.get("blade_thickness_limits_mm"), positive=True)
        and arbor.get("envelope_state") == "complete"
        and arbor.get("cutting_rotation") in ("cw", "ccw")
        and arbor.get("retaining_side") in ("minus_z", "plus_z")
        and arbor.get("retaining_thread_hand") in ("right", "left")
        and mounted.get("spindle_rotation") in ("cw", "ccw")
    )
    components = arbor.get("components")
    complete = complete and isinstance(components, list) and bool(components)
    if isinstance(components, list):
        identities = []
        for component in components:
            component = record(component)
            identity_ = component.get("id")
            identities.append(identity_)
            complete = complete and (
                isinstance(identity_, str)
                and bool(identity_.strip())
                and all(
                    _saw_number(component.get(key)) for key in ("dia_mm", "z_min_mm", "z_max_mm")
                )
                and component["dia_mm"] > 0
                and component["z_min_mm"] < component["z_max_mm"]
            )
        complete = complete and len(identities) == len(set(map(str, identities)))
    if not complete:
        reasons.append("complete measured finite-disk blade and mounted arbor assembly are unknown")
    return (UNKNOWN, list(dict.fromkeys(reasons))) if reasons else ("pass", [])


def _saw_bounds(value):
    """The native setup-mm bbox convention: xmin,ymin,zmin,xmax,ymax,zmax."""
    return (
        isinstance(value, list)
        and len(value) == 6
        and all(_saw_number(v) for v in value)
        and all(value[i] <= value[i + 3] for i in range(3))
    )


def _saw_union_bounds(bounds, addition):
    """Keep each known range; an incomplete original remains separate proof debt."""
    result = list(addition)
    if isinstance(bounds, list) and len(bounds) == 6:
        for axis in range(3):
            band = [bounds[axis], bounds[axis + 3]]
            if _saw_band(band):
                result[axis] = min(result[axis], band[0])
                result[axis + 3] = max(result[axis + 3], band[1])
    return result


def _saw_machine_bounds(saw, keys):
    """Union trajectory and selected calibration ranges, never omitting unknown motion."""
    missing = [key for key in keys if not _saw_bounds(saw.get(key))]
    zero = record(saw.get("zero"))
    selected, touches = zero.get("selected"), zero.get("touches")
    chosen = [
        record(touch)
        for touch in (touches if isinstance(touches, list) else [])
        if record(touch).get("index") == selected
    ]
    if (
        not isinstance(selected, int)
        or isinstance(selected, bool)
        or selected < 0
        or len(chosen) != 1
        or not isinstance(chosen[0].get("index"), int)
        or isinstance(chosen[0]["index"], bool)
    ):
        return saw, [*missing, "selected calibration approach"]
    touch = chosen[0]
    if zero.get("status") != "pass" or touch.get("status") != "pass":
        missing.append("selected calibration approach")
    axis = touch.get("axis_xy_mm")
    endpoints = [touch.get(key) for key in ("approach_start_z_mm", "approach_end_z_mm")]
    band = saw.get("cutting_band_mm")
    nose, kerf_offset = saw.get("spindle_nose_z_mm"), touch.get("kerf_offset_mm")
    if not (
        isinstance(axis, list)
        and len(axis) == 2
        and all(_saw_number(value) for value in [*axis, *endpoints, nose, kerf_offset])
        and endpoints[0] != endpoints[1]
        and _saw_band(band)
        and band[0] < band[1]
    ):
        return saw, [*missing, "calibration axis and spindle-nose ranges"]
    # The cutting band is centred on the operation's cutting midplane. The
    # nose offset is fixed by this measured mounted assembly, also during setting.
    nose_offset = nose - (band[0] + band[1]) / 2
    axis_z = [z + offset for z in endpoints for offset in (-kerf_offset, nose_offset)]
    nose_z = [z + nose_offset for z in endpoints]
    result = {
        **saw,
        "axis_path_bounds_mm": _saw_union_bounds(
            saw.get("axis_path_bounds_mm"), [*axis, min(axis_z), *axis, max(axis_z)]
        ),
        "spindle_nose_bounds_mm": _saw_union_bounds(
            saw.get("spindle_nose_bounds_mm"), [*axis, min(nose_z), *axis, max(nose_z)]
        ),
    }
    swept = touch.get("assembly_swept_bounds_mm")
    if _saw_bounds(swept):
        result["assembly_swept_bounds_mm"] = _saw_union_bounds(
            saw.get("assembly_swept_bounds_mm"), swept
        )
    else:
        missing.append("calibration assembly_swept_bounds_mm")
    return result, list(dict.fromkeys(missing))


def finite_saw_evidence(detail, check):
    """Consume complete evidence for one check, never a model or status marker alone."""
    detail = record(detail)
    saw = record(detail.get("saw"))
    if saw.get("model") != "finite_disk_v1":
        return UNKNOWN, [SLITTING_SAW_MODEL_REASON], saw
    reasons = _saw_reasons(saw.get("reasons"))
    if check in {"envelope", "headroom", "travel"}:
        keys = (
            ("axis_path_bounds_mm",)
            if check == "travel"
            else ("assembly_swept_bounds_mm", "spindle_nose_bounds_mm")
        )
        evidence, missing = _saw_machine_bounds(saw, keys)
        if saw.get("status") != "pass":
            missing.append("successful native saw proof")
        return (
            (UNKNOWN, [f"finite saw {', '.join(missing)} are unresolved"], evidence)
            if missing
            else ("pass", [], evidence)
        )
    if check == "engagement":
        engagement = record(saw.get("engagement"))
        why = _saw_reasons(engagement.get("reasons"))
        count = engagement.get("minimum_teeth_in_work")
        complete = (
            engagement.get("status") == "pass"
            and _saw_band(engagement.get("established_interval_mm"))
            and engagement["established_interval_mm"][0] < engagement["established_interval_mm"][1]
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
            and isinstance(engagement.get("tooth_count"), int)
            and not isinstance(engagement["tooth_count"], bool)
            and engagement["tooth_count"] > 0
            and engagement.get("tooth_spacing") == "uniform"
            and count <= engagement["tooth_count"]
            and isinstance(engagement.get("minimum_teeth_tie"), bool)
            and all(
                _saw_number(engagement.get(key))
                for key in (
                    "radius_mm",
                    "first_contact_mm",
                    "entry_complete_mm",
                    "exit_begins_mm",
                    "last_contact_mm",
                    "engaged_angle_rad",
                    "pitch_rad",
                )
            )
            and engagement["radius_mm"] > 0
            and engagement["pitch_rad"] > 0
            and engagement["engaged_angle_rad"] > 0
            and _saw_band(engagement.get("transverse_interval_mm"))
            and engagement["first_contact_mm"]
            < engagement["entry_complete_mm"]
            < engagement["exit_begins_mm"]
            < engagement["last_contact_mm"]
            and engagement["established_interval_mm"]
            == [engagement["entry_complete_mm"], engagement["exit_begins_mm"]]
            and all(
                isinstance(engagement.get(key), dict)
                and _saw_number(engagement[key].get("from_mm"))
                and _saw_number(engagement[key].get("to_mm"))
                and engagement[key]["from_mm"] < engagement[key]["to_mm"]
                and engagement[key].get("monotone") is True
                and engagement[key].get("tooth_loading_certified") is False
                for key in ("entry", "exit")
            )
        )
        if engagement.get("status") == "error":
            return "error", why or ["native circular engagement is invalid"], saw
        return (
            ("pass", [], saw)
            if complete and not why
            else (
                UNKNOWN,
                why or ["complete established circular tooth engagement is unresolved"],
                saw,
            )
        )
    if check == "zero":
        zero = record(saw.get("zero"))
        why = _saw_reasons(zero.get("reasons"))
        touches = zero.get("touches")
        selected = zero.get("selected")
        chosen = next(
            (
                record(touch)
                for touch in (touches if isinstance(touches, list) else [])
                if record(touch).get("index") == selected
            ),
            {},
        )
        if zero.get("status") == "error" or chosen.get("status") == "error":
            return (
                "error",
                why + _saw_reasons(chosen.get("reasons"))
                or ["mounted blade calibration contact is invalid"],
                saw,
            )
        scalar_keys = (
            "plane_z_mm",
            "plane_normal_z",
            "paper_mm",
            "body_thickness_mm",
            "kerf_offset_mm",
            "body_face_z_mm",
            "cutting_midplane_z_mm",
            "contact_radius_mm",
            "exposed_inner_radius_mm",
            "root_radius_mm",
            "approach_start_z_mm",
            "approach_end_z_mm",
        )
        complete = (
            zero.get("status") == "pass"
            and not why
            and isinstance(selected, int)
            and not isinstance(selected, bool)
            and selected >= 0
            and isinstance(chosen.get("index"), int)
            and not isinstance(chosen["index"], bool)
            and sum(
                record(touch).get("index") == selected
                for touch in (touches if isinstance(touches, list) else [])
            )
            == 1
            and chosen.get("status") == "pass"
            and not _saw_reasons(chosen.get("reasons"))
            and all(_saw_number(chosen.get(key)) for key in scalar_keys)
            and chosen.get("spindle_state") == "stopped"
            and chosen.get("blade_side") in ("minus_z", "plus_z")
            and chosen.get("surface_side") in ("+z", "-z")
            and chosen.get("collisions") == []
            and isinstance(chosen.get("point_mm"), list)
            and len(chosen["point_mm"]) == 3
            and all(_saw_number(v) for v in chosen["point_mm"])
            and isinstance(chosen.get("axis_xy_mm"), list)
            and len(chosen["axis_xy_mm"]) == 2
            and all(_saw_number(v) for v in chosen["axis_xy_mm"])
        )
        if complete:
            side = 1 if chosen["blade_side"] == "minus_z" else -1
            expected = (
                chosen["plane_z_mm"]
                + side * (chosen["paper_mm"] + chosen["body_thickness_mm"] / 2)
                + chosen["kerf_offset_mm"]
            )
            complete = (
                chosen["body_thickness_mm"] > 0
                and chosen["paper_mm"] >= 0
                and chosen["plane_normal_z"] == side
                and chosen["surface_side"] == ("+z" if side == 1 else "-z")
                and 0
                <= chosen["exposed_inner_radius_mm"]
                < chosen["contact_radius_mm"]
                < chosen["root_radius_mm"]
                and math.isclose(chosen["cutting_midplane_z_mm"], expected, rel_tol=0, abs_tol=1e-6)
                and math.isclose(
                    chosen["approach_end_z_mm"],
                    chosen["cutting_midplane_z_mm"],
                    rel_tol=0,
                    abs_tol=1e-6,
                )
                and math.isclose(
                    chosen["point_mm"][2], chosen["plane_z_mm"], rel_tol=0, abs_tol=1e-6
                )
                and math.isclose(
                    chosen["body_face_z_mm"],
                    chosen["plane_z_mm"] + side * chosen["paper_mm"],
                    rel_tol=0,
                    abs_tol=1e-6,
                )
                and math.isclose(
                    chosen["contact_radius_mm"],
                    math.hypot(
                        chosen["point_mm"][0] - chosen["axis_xy_mm"][0],
                        chosen["point_mm"][1] - chosen["axis_xy_mm"][1],
                    ),
                    rel_tol=0,
                    abs_tol=1e-6,
                )
                and chosen["approach_start_z_mm"] != chosen["approach_end_z_mm"]
            )
        return (
            ("pass", [], saw)
            if complete
            else (
                UNKNOWN,
                why or ["complete mounted blade contact and axial approach are unresolved"],
                saw,
            )
        )
    if check not in {"geometry", "accessibility", "reach"}:
        raise ValueError(f"unknown finite saw evidence check: {check}")
    error = _saw_reasons(detail.get("saw_error"))
    error.extend(_saw_reasons(saw.get("errors")))
    collisions = saw.get("collisions")
    if isinstance(collisions, list) and collisions:
        error.append("finite blade or arbor sweep collides with stock or a fixture")
    for key, why in (
        ("uncovered_kerf_volume_mm3", "finite cutting sweep leaves an uncut kerf or ligament"),
        ("unintended_removal_volume_mm3", "finite cutting sweep removes protected material"),
    ):
        if _saw_number(saw.get(key)) and saw[key] > 0:
            error.append(why)
    if saw.get("status") == "error":
        error.extend(reasons or ["native finite saw geometry is invalid"])
    if error:
        return "error", list(dict.fromkeys(error)), saw
    bands = (saw.get("body_band_mm"), saw.get("cutting_band_mm"))
    complete = (
        saw.get("status") == "pass"
        and not reasons
        and all(_saw_band(band) and band[0] < band[1] for band in bands)
        and bands[1][0] <= bands[0][0] <= bands[0][1] <= bands[1][1]
        and all(
            _saw_bounds(saw.get(key))
            for key in (
                "axis_path_bounds_mm",
                "assembly_swept_bounds_mm",
                "spindle_nose_bounds_mm",
            )
        )
        and isinstance(collisions, list)
        and not collisions
        and _saw_number(saw.get("gauge_plane_z_mm"))
        and _saw_number(saw.get("spindle_nose_z_mm"))
        and isinstance(saw.get("cut_move_index"), int)
        and not isinstance(saw["cut_move_index"], bool)
        and saw["cut_move_index"] >= 0
        and isinstance(saw.get("feed_direction"), list)
        and len(saw["feed_direction"]) == 3
        and all(_saw_number(v) for v in saw["feed_direction"])
        and saw["feed_direction"][2] == 0
        and sum(v != 0 for v in saw["feed_direction"]) == 1
        and record(saw.get("capture")).get("status") == "pass"
        and not _saw_reasons(record(saw.get("capture")).get("reasons"))
        and isinstance(record(saw.get("capture")).get("contacts"), list)
        and bool(saw["capture"]["contacts"])
        and all(isinstance(name, str) and name.strip() for name in saw["capture"]["contacts"])
        and saw["capture"].get("moving_clamp_contact") is True
    )
    for key in (
        "required_kerf_volume_mm3",
        "uncovered_kerf_volume_mm3",
        "removed_kerf_volume_mm3",
        "unintended_removal_volume_mm3",
        "stock_volume_before_mm3",
        "stock_volume_after_mm3",
    ):
        complete = complete and _saw_number(saw.get(key)) and saw[key] >= 0
    if complete:
        complete = (
            saw["required_kerf_volume_mm3"] > 0
            and saw["removed_kerf_volume_mm3"] > 0
            and saw["uncovered_kerf_volume_mm3"] == 0
            and saw["unintended_removal_volume_mm3"] == 0
            and saw["stock_volume_before_mm3"] > saw["stock_volume_after_mm3"] > 0
        )
    outputs = saw.get("outputs")
    complete = complete and isinstance(outputs, list) and len(outputs) == 2
    if isinstance(outputs, list):
        for output in outputs:
            output = record(output)
            complete = (
                complete
                and _saw_number(output.get("volume_mm3"))
                and output["volume_mm3"] > 0
                and _saw_bounds(output.get("bbox_mm"))
                and output.get("side") in ("below", "above")
            )
    if complete:
        complete = [output["side"] for output in outputs] == ["below", "above"]
    return (
        ("pass", [], saw)
        if complete
        else (
            UNKNOWN,
            reasons or ["complete finite-disk kerf and assembly proof is unresolved"],
            saw,
        )
    )


def op_contexts(bundle, rule, required=(), fixture=False, stock=True, turning=None):
    """Per-op context; ``turning`` names the required inputs of turning-model ops."""
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    job = prepared_job(bundle)
    jobs = {op["subject"]: op for setup in job["setups"] for op in setup["ops"]}
    holds = {setup["id"]: setup["hold"] for setup in job["setups"]}
    frames = {setup["id"]: setup["frame"] for setup in job["setups"]}
    for setup, op in operations(bundle):
        subject = f"{setup['id']}:{op['op']}"
        cite = provenance(bundle, rule, setup, op, op_feature(op))
        if op.get("do") in SAW_OPS:
            disk = spindle_saw(bundle, setup, op) and rule in {"accessibility", "reach"}
            inputs = jobs.get(subject, {})
            detail = record(record(facts.get("ops")).get(subject))
            status, why, saw = (
                finite_saw_evidence(detail, rule)
                if disk
                else ("not_applicable", [SAW_TOOL_MODEL_REASON], {})
            )
            if disk and not slitting_saw(bundle, op):
                status, why = UNKNOWN, [UNRESOLVED_SAW_MODEL_REASON]
            if disk:
                assembly_status, assembly_reasons = mounted_saw_assembly_evidence(
                    inputs.get("mounted_saw")
                )
                if assembly_status == "error" or (status == "pass" and assembly_status != "pass"):
                    status, why = assembly_status, assembly_reasons
                blocked = unavailable(bundle, rule, subject, facts, cite)
                if blocked and status != "error":
                    status, why = blocked.status, [blocked.sentence]
            message = (
                "; ".join(why)
                if why
                else (
                    "the exact finite blade and arbor sweeps clear stock and fixtures"
                    if rule == "accessibility"
                    else (
                        "the finite cutting sweep covers the required kerf "
                        "with the body and arbor clear"
                    )
                )
            )
            entries = kernel_measurement_debts(job, setup, op, fixture=fixture, stock=stock)
            finding = with_measurement_debts(
                Finding(
                    rule,
                    subject,
                    status,
                    {
                        "operation": op["do"],
                        **({"saw": saw} if saw else {}),
                        **({"model_reason": message} if disk and status == UNKNOWN else {}),
                    },
                    cite,
                    f"{subject}: {message}.",
                ),
                entries,
            )
            yield setup, op, facts, detail, {**inputs, "measurement_debts": entries}, cite, finding
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
        inputs = {
            **inputs,
            "measurement_debts": kernel_measurement_debts(
                job,
                setup,
                op,
                fixture=fixture,
                stock=stock and bool(detail.get("stock_reason")),
            ),
        }
        if blocked is None:
            if cutting_action(op) is False:
                blocked = Finding(
                    rule,
                    subject,
                    "not_applicable",
                    {},
                    cite,
                    f"{subject}: {op['do']} is bench filing; no machine cutter reaches the part."
                    if op.get("do") in HAND_FINISH
                    else f"{subject}: {op['do']} does not cut geometry.",
                )
            elif cutting_action(op) is None:
                blocked = Finding(
                    rule, subject, "unknown", {}, cite, f"{subject}: cutting action is unknown."
                )
            else:
                claims, away, invalid = op_claims(bundle, facts, setup, op)
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
                elif (
                    registered_workpieces(bundle)
                    and claims is None
                    or not known_refs(claim_refs(bundle, op, setup))
                    or (
                        approach_reason
                        and any(
                            ref not in face_mapping(bundle, facts, setup)
                            for ref in claim_refs(bundle, op, setup)
                        )
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
                elif turned and _clamped_head(inputs):
                    blocked = Finding(
                        rule,
                        subject,
                        "unknown",
                        {
                            "projection_mm": inputs["projection_mm"],
                            "head_len_mm": inputs["head_len_mm"],
                        },
                        cite,
                        f"{subject}: the tool is set {inputs['projection_mm']:g} mm out of its "
                        f"holder, shorter than its {inputs['head_len_mm']:g} mm head, so the "
                        "holder clamps the head and its clearance is not modelled: set "
                        "projection_mm at least head_len_mm.",
                    )
                    # Both comparison inputs are accepted facts. This setting refuses
                    # placement before fixture, DRO or reach facts can decide clearance.
                    yield setup, op, facts, detail, inputs, cite, blocked
                    continue
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
        if blocked is not None:
            blocked = with_measurement_debts(blocked, inputs["measurement_debts"])
        yield setup, op, facts, detail, inputs, cite, blocked


def _clamped_head(inputs):
    """A turning tool set out of its holder by less than its head length."""
    projection, head = inputs.get("projection_mm"), inputs.get("head_len_mm")
    return number(projection) and number(head) and projection < head


def setup_contexts(bundle, rule):
    from prechips.kernel import run_geometry

    facts = run_geometry(bundle)
    job = prepared_job(bundle)
    holds = {s["id"]: s["hold"] for s in job["setups"]}
    frames = {s["id"]: s["frame"] for s in job["setups"]}
    for setup in bundle.plan["setups"]:
        subject = setup["id"]
        cite = provenance(bundle, rule, setup)
        inputs = holds[subject]
        detail = record(record(facts.get("setups")).get(subject))
        blocked = unavailable(bundle, rule, subject, facts, cite)
        unloaded = rule == "thin_wall_under_clamp" and unclamped_noncutting(setup, inputs)
        inputs = {
            **inputs,
            "measurement_debts": kernel_measurement_debts(
                job, setup, fixture=True, stock=bool(detail.get("stock_reason"))
            ),
        }
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
            elif inputs["kind"] == HAND_FED:
                blocked = Finding(
                    rule,
                    subject,
                    "not_applicable",
                    {"hold_kind": HAND_FED},
                    cite,
                    f"{subject}: the work is fed by hand on the saw table; no fixture, jaw or "
                    "clamp holds it.",
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
        if blocked is not None:
            blocked = with_measurement_debts(blocked, inputs["measurement_debts"])
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
